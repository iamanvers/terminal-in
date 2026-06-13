'use client'
import { THEME } from '@/lib/theme'
/**
 * LEARN MODULE — comprehensive, curated market education.
 * Free (mostly) resources organized into tracks that span the full path:
 * foundations → technical → fundamental → derivatives → quant → ML/AI →
 * risk → macro → regulation/tax → this terminal → the canon. Each resource
 * is tagged by level and kind. All links open externally.
 */
import React, { useMemo, useState } from 'react'

const C = THEME

type Level = 'beginner' | 'intermediate' | 'advanced'
type Kind = 'course' | 'article' | 'book' | 'paper' | 'tool' | 'official'
type Resource = { title: string; url: string; desc: string; level: Level; kind: Kind }
type Track = { id: string; label: string; color: string; blurb: string; resources: Resource[] }

const TRACKS: Track[] = [
  {
    id: 'foundations', label: 'FOUNDATIONS', color: C.green,
    blurb: 'Market mechanics, instruments, and how Indian markets actually work — start here.',
    resources: [
      { title: 'Varsity — Introduction to Stock Markets', url: 'https://zerodha.com/varsity/module/introduction-to-stock-markets/', desc: 'The canonical free Indian-markets course. Exchanges, IPOs, settlement, participants, the regulatory frame.', level: 'beginner', kind: 'course' },
      { title: 'NSE — Investor education & knowledge hub', url: 'https://www.nseindia.com/invest/about-investor-education', desc: 'The exchange’s own primers on products, the order book, circuit limits, and how matching works.', level: 'beginner', kind: 'official' },
      { title: 'SEBI Investor (saa₹thi) portal', url: 'https://investor.sebi.gov.in/', desc: 'The regulator’s investor-education hub: rights, grievance redress, do’s and don’ts, and verified basics.', level: 'beginner', kind: 'official' },
      { title: 'Investopedia — Stock Market Basics', url: 'https://www.investopedia.com/articles/basics/06/invest1000.asp', desc: 'Global reference for any term you hit anywhere in this app.', level: 'beginner', kind: 'article' },
      { title: 'Varsity — Personal Finance', url: 'https://zerodha.com/varsity/module/personal-finance/', desc: 'Compounding, mutual funds, bonds, asset allocation — the wider context a single book sits inside.', level: 'beginner', kind: 'course' },
    ],
  },
  {
    id: 'technical', label: 'TECHNICAL ANALYSIS', color: C.blue,
    blurb: 'Charts, indicators, and price/volume patterns — the vocabulary this terminal’s lenses speak.',
    resources: [
      { title: 'Varsity — Technical Analysis', url: 'https://zerodha.com/varsity/module/technical-analysis/', desc: 'Candlesticks, support/resistance, volumes, RSI/MACD/EMA — exactly the indicators S2/S4/S5 compute.', level: 'beginner', kind: 'course' },
      { title: 'StockCharts — ChartSchool', url: 'https://chartschool.stockcharts.com/', desc: 'Deep, free encyclopedia of every indicator and chart pattern, with the underlying formulas.', level: 'intermediate', kind: 'article' },
      { title: 'Investopedia — Technical Analysis guide', url: 'https://www.investopedia.com/technical-analysis-4689657', desc: 'Structured reference: trend, momentum, volatility, and volume families.', level: 'beginner', kind: 'article' },
      { title: 'Aronson — Evidence-Based Technical Analysis', url: 'https://www.wiley.com/en-us/Evidence+Based+Technical+Analysis-p-9780470008744', desc: 'The skeptic’s text: which TA actually survives statistical scrutiny, and why most doesn’t.', level: 'advanced', kind: 'book' },
    ],
  },
  {
    id: 'fundamental', label: 'FUNDAMENTAL ANALYSIS', color: C.teal,
    blurb: 'Reading the business behind the ticker — the data plane M6 (world model) will fuse with price.',
    resources: [
      { title: 'Varsity — Fundamental Analysis', url: 'https://zerodha.com/varsity/module/fundamental-analysis/', desc: 'P&L, balance sheet, cash flow, ratios, DCF — reading an annual report end to end.', level: 'intermediate', kind: 'course' },
      { title: 'Screener.in', url: 'https://www.screener.in/', desc: 'Free Indian-equity fundamentals + screening: 10-yr financials, ratios, quarterly results. The likely M6 fundamentals source.', level: 'intermediate', kind: 'tool' },
      { title: 'Tijori Finance', url: 'https://www.tijorifinance.com/', desc: 'Visual fundamentals, segment/peer breakdowns, and supply-chain maps — the “how it ties back” relational view.', level: 'intermediate', kind: 'tool' },
      { title: 'Damodaran — Valuation (NYU, free)', url: 'https://pages.stern.nyu.edu/~adamodar/', desc: 'The definitive open valuation resource: lecture notes, spreadsheets, and India risk-premium data.', level: 'advanced', kind: 'course' },
      { title: 'Graham — The Intelligent Investor', url: 'https://www.wiley.com/en-us/The+Intelligent+Investor%2C+Rev.+Ed-p-9780060555665', desc: 'Margin of safety and Mr. Market — the long-horizon counterweight to the technical lenses.', level: 'intermediate', kind: 'book' },
    ],
  },
  {
    id: 'derivatives', label: 'F&O / DERIVATIVES', color: C.purple,
    blurb: 'Futures, options, greeks, and strategies — the machinery the F&O module implements in P2.',
    resources: [
      { title: 'Varsity — Futures Trading', url: 'https://zerodha.com/varsity/module/futures-trading/', desc: 'Contracts, margins (SPAN), leverage, mark-to-market, settlement — exactly what F&O execution needs.', level: 'intermediate', kind: 'course' },
      { title: 'Varsity — Options Theory for Professionals', url: 'https://zerodha.com/varsity/module/option-theory/', desc: 'Greeks, moneyness, the volatility smile. The best free options text for Indian markets.', level: 'intermediate', kind: 'course' },
      { title: 'Varsity — Option Strategies', url: 'https://zerodha.com/varsity/module/option-strategies/', desc: 'Spreads, straddles, condors — the multi-leg playbook planned for P3.', level: 'advanced', kind: 'course' },
      { title: 'NSE — Derivatives (F&O) product notes', url: 'https://www.nseindia.com/products-services/equity-derivatives-watch', desc: 'Official contract specs, lot sizes, expiries, and margin framework — the source contract_specs.py mirrors.', level: 'intermediate', kind: 'official' },
      { title: 'Hull — Options, Futures, and Other Derivatives', url: 'https://www.pearson.com/en-us/subject-catalog/p/options-futures-and-other-derivatives/P200000005938', desc: 'The graduate-standard derivatives text: pricing, greeks, exotics, risk-neutral valuation.', level: 'advanced', kind: 'book' },
    ],
  },
  {
    id: 'quant', label: 'QUANT & SYSTEMATIC', color: C.accent,
    blurb: 'The discipline behind this terminal: signals, backtesting, stat-arb, and microstructure.',
    resources: [
      { title: 'Varsity — Trading Systems', url: 'https://zerodha.com/varsity/module/trading-systems/', desc: 'Building rule-based systems — the philosophy behind the 8 strategies and the orchestrator lenses.', level: 'intermediate', kind: 'course' },
      { title: 'QuantStart — Articles', url: 'https://www.quantstart.com/articles/', desc: 'Free deep-dives on backtesting, stat-arb, and portfolio construction in Python.', level: 'advanced', kind: 'article' },
      { title: 'QuantInsti — Blog', url: 'https://blog.quantinsti.com/', desc: 'Algorithmic-trading tutorials with an India/Zerodha bent: strategy coding, execution, risk.', level: 'intermediate', kind: 'article' },
      { title: 'López de Prado — Advances in Financial Machine Learning', url: 'https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086', desc: 'Why naive backtests lie: labelling, cross-validation leakage, feature importance, walk-forward. Essential before trusting a backtest.', level: 'advanced', kind: 'book' },
      { title: 'Harris — Trading and Exchanges (microstructure)', url: 'https://global.oup.com/academic/product/trading-and-exchanges-9780195144703', desc: 'How orders, liquidity, and matching really work — the ground truth under every fill model.', level: 'advanced', kind: 'book' },
    ],
  },
  {
    id: 'mlai', label: 'ML & AI FOR MARKETS', color: C.accentBright,
    blurb: 'The models this terminal trains — and the research behind Module 6 (the world-model judge).',
    resources: [
      { title: 'Chang et al. — Forecasting & Automated Trading with Deep Learning (2026)', url: 'https://doi.org/10.3390/engproc2026128042', desc: 'LSTM + sentiment + rules on the TWSE. Honest result: it underperforms buy-and-hold in 2 of 3 horizons — why reactive prediction alone isn’t an edge.', level: 'advanced', kind: 'paper' },
      { title: 'Zhu et al. — LSTM-RF Directional Model Selection (2026)', url: 'https://doi.org/10.3390/info17060548', desc: 'Different models own different directions; pick by trailing hit-rate. The basis for M6’s directional-competence layer (Phase C).', level: 'advanced', kind: 'paper' },
      { title: 'LeCun — A Path Towards Autonomous Machine Intelligence (JEPA)', url: 'https://openreview.net/forum?id=BZ5a1r-kVsf', desc: 'The position paper behind JEPA: predict in representation space, not input space. The core of M6’s market-state encoder.', level: 'advanced', kind: 'paper' },
      { title: 'Ha & Schmidhuber — World Models', url: 'https://worldmodels.github.io/', desc: 'Learn a latent dynamics model and plan by “imagining” forward — the forward-simulation M6 adds to the judge.', level: 'advanced', kind: 'paper' },
      { title: 'Hafner et al. — DreamerV3', url: 'https://arxiv.org/abs/2301.04104', desc: 'Mastering tasks by RL inside a learned world model — the template for M6’s optional latent policy (Phase E).', level: 'advanced', kind: 'paper' },
      { title: 'FinBERT — Financial sentiment (Araci, 2019)', url: 'https://arxiv.org/abs/1908.10063', desc: 'The sentiment model already wired into the news pipeline and the M6 news/sentiment plane.', level: 'intermediate', kind: 'paper' },
      { title: 'Stanford CS229 — Machine Learning (free)', url: 'https://cs229.stanford.edu/', desc: 'The foundations (regression, SVM, trees, neural nets) under every model name in this app.', level: 'intermediate', kind: 'course' },
    ],
  },
  {
    id: 'risk', label: 'RISK & PSYCHOLOGY', color: C.warn,
    blurb: 'Position sizing, drawdowns, and behavior — why the M2 gate and the supervisor exist.',
    resources: [
      { title: 'Varsity — Risk Management & Trading Psychology', url: 'https://zerodha.com/varsity/module/risk-management-trading-psychology/', desc: 'Position sizing, drawdowns, Kelly, and the behavioral traps the deterministic gate is designed to remove.', level: 'intermediate', kind: 'course' },
      { title: 'Investopedia — Kelly Criterion', url: 'https://www.investopedia.com/terms/k/kellycriterion.asp', desc: 'Optimal bet sizing — the orchestrator sizes at fractional Kelly scaled by the regime multiplier.', level: 'intermediate', kind: 'article' },
      { title: 'Investopedia — Sharpe, Sortino & Max Drawdown', url: 'https://www.investopedia.com/terms/s/sharperatio.asp', desc: 'The risk-adjusted metrics the backtest engine and scorecards report — and how to read them honestly.', level: 'intermediate', kind: 'article' },
      { title: 'Kahneman — Thinking, Fast and Slow', url: 'https://us.macmillan.com/books/9780374533557/thinkingfastandslow', desc: 'System 1 vs System 2 — the same dual-process framing M6 uses (world model = intuition, SLM = deliberation).', level: 'beginner', kind: 'book' },
    ],
  },
  {
    id: 'macro', label: 'MACRO & ECONOMY', color: C.steel,
    blurb: 'Rates, inflation, FX, and global linkages — the macro plane that drives regime and factors.',
    resources: [
      { title: 'RBI — Monetary Policy', url: 'https://www.rbi.org.in/Scripts/BS_ViewMonetaryPolicy.aspx', desc: 'Repo decisions, the policy stance, and the MPC minutes that move the whole rate curve and banking complex.', level: 'intermediate', kind: 'official' },
      { title: 'MoSPI — CPI & IIP releases', url: 'https://www.mospi.gov.in/', desc: 'Official inflation and industrial-production prints — primary macro inputs, not second-hand summaries.', level: 'intermediate', kind: 'official' },
      { title: 'Trading Economics — India', url: 'https://tradingeconomics.com/india/indicators', desc: 'One dashboard for India’s rates, inflation, FX, trade, and the calendar of upcoming prints.', level: 'beginner', kind: 'tool' },
      { title: 'Varsity — Currency, Commodity & Government Securities', url: 'https://zerodha.com/varsity/module/currency-commodities-and-government-securities/', desc: 'USDINR, crude, gold, and bonds — the cross-asset drivers behind P3 multi-asset and the macro plane.', level: 'intermediate', kind: 'course' },
    ],
  },
  {
    id: 'regtax', label: 'REGULATION & TAX', color: C.blue,
    blurb: 'The rules an Indian trader operates under — compliance, and what the taxman takes.',
    resources: [
      { title: 'Varsity — Markets & Taxation', url: 'https://zerodha.com/varsity/module/markets-and-taxation/', desc: 'STCG/LTCG, speculative vs business income, turnover, audit, and carrying forward losses — for Indian traders specifically.', level: 'intermediate', kind: 'course' },
      { title: 'SEBI — Official site', url: 'https://www.sebi.gov.in/', desc: 'The source for circulars, margin rules, and the regulations the risk gate and event masks must respect.', level: 'advanced', kind: 'official' },
      { title: 'ClearTax — Capital Gains on Shares', url: 'https://cleartax.in/s/capital-gains-income', desc: 'Plain-language guide to taxing equity/F&O gains in India, with current rates and examples.', level: 'beginner', kind: 'article' },
      { title: 'NSE — Circulars', url: 'https://www.nseindia.com/regulations/exchange-circulars', desc: 'Lot-size revisions, holiday calendar, and ban-period lists — the feeds contract specs and market-hours logic track.', level: 'advanced', kind: 'official' },
    ],
  },
  {
    id: 'terminal', label: 'THIS TERMINAL', color: C.accentMid,
    blurb: 'The concepts TERMINAL//IN itself runs on — what the badges, gates, and verdicts mean.',
    resources: [
      { title: 'Expected Value (EV) ranking', url: 'https://www.investopedia.com/terms/e/expected-value.asp', desc: 'EV = confidence × reward:risk × volume factor × lens convergence. Signals fire only above EV 1.2 with hysteresis at 1.0.', level: 'beginner', kind: 'article' },
      { title: 'Hidden Markov Models (regime)', url: 'https://www.investopedia.com/terms/r/regime-switching-models.asp', desc: 'The 6-state regime classifier (strong_bull → high_vol) now trained on 10y of data, scaling all position sizing.', level: 'advanced', kind: 'article' },
      { title: 'Bayesian win-rate updating', url: 'https://www.investopedia.com/terms/b/bayes-theorem.asp', desc: 'How the StrategyLearner and DSA weight strategies by their actual record, not hope.', level: 'intermediate', kind: 'article' },
      { title: 'Walk-forward analysis', url: 'https://www.investopedia.com/terms/w/walk-forward-analysis.asp', desc: 'The only honest way to validate a system on history — what the backtest engine reports per year.', level: 'advanced', kind: 'article' },
      { title: 'Project docs — PRD, README, World-Model design', url: 'https://github.com/iamanvers/terminal-in', desc: 'The terminal’s own product requirements, architecture, and the Module 6 (world-model judge) design.', level: 'advanced', kind: 'official' },
    ],
  },
]

const LEVEL_C: Record<Level, string> = { beginner: C.green, intermediate: C.warn, advanced: C.red }
const KIND_LABEL: Record<Kind, string> = {
  course: 'COURSE', article: 'ARTICLE', book: 'BOOK', paper: 'PAPER', tool: 'TOOL', official: 'OFFICIAL',
}

export default function LearnPage() {
  const [track, setTrack] = useState<string>(TRACKS[0].id)
  const [level, setLevel] = useState<Level | 'all'>('all')
  const active = TRACKS.find(t => t.id === track) ?? TRACKS[0]
  const rows = useMemo(
    () => level === 'all' ? active.resources : active.resources.filter(r => r.level === level),
    [active, level],
  )
  const total = useMemo(() => TRACKS.reduce((n, t) => n + t.resources.length, 0), [])

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: 'transparent', overflow: 'hidden' }}>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '12px 16px', flexShrink: 0, display: 'flex', alignItems: 'flex-end', gap: 16 }}>
        <div style={{ flex: 1 }}>
          <div className="t-display" style={{ fontSize: 17 }}>Market Education</div>
          <div className="t-prose" style={{ fontSize: 11.5, marginTop: 2 }}>
            A full path from market mechanics to the machine-learning research behind this terminal —
            Zerodha Varsity, exchange/regulator primaries, the quant canon, and the papers under Module 6.
            All links open externally.
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.accent, fontVariantNumeric: 'tabular-nums' }}>{total}</div>
          <div style={{ fontSize: 9, color: C.muted, letterSpacing: '.08em' }}>RESOURCES · {TRACKS.length} TRACKS</div>
        </div>
      </div>

      {/* Track selector */}
      <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap' }}>
        {TRACKS.map(t => (
          <button key={t.id} onClick={() => setTrack(t.id)} style={{
            fontSize: 10, fontWeight: 700, letterSpacing: '.07em', padding: '7px 13px',
            borderRadius: 4, cursor: 'pointer',
            border: `1px solid ${track === t.id ? t.color + '66' : C.border}`,
            background: track === t.id ? `${t.color}0E` : C.panel,
            color: track === t.id ? t.color : C.muted,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Blurb + level filter */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0, padding: '0 2px' }}>
        <div style={{ fontSize: 10.5, color: C.muted, flex: 1 }}>{active.blurb}</div>
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          {(['all', 'beginner', 'intermediate', 'advanced'] as const).map(lv => (
            <button key={lv} onClick={() => setLevel(lv)} style={{
              fontSize: 9, fontWeight: 700, letterSpacing: '.06em', padding: '3px 9px', borderRadius: 3, cursor: 'pointer',
              textTransform: 'uppercase',
              border: `1px solid ${level === lv ? (lv === 'all' ? C.accent : LEVEL_C[lv]) + '66' : C.border}`,
              background: level === lv ? (lv === 'all' ? C.accent : LEVEL_C[lv]) + '12' : 'transparent',
              color: level === lv ? (lv === 'all' ? C.accent : LEVEL_C[lv]) : C.dim,
            }}>{lv}</button>
          ))}
        </div>
      </div>

      {/* Resource cards */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 8, alignContent: 'start' }}>
        {rows.map(r => (
          <a key={r.url} href={r.url} target="_blank" rel="noopener noreferrer" style={{
            display: 'block', padding: '12px 14px', background: C.card,
            border: `1px solid ${C.border}`, borderRadius: 5, textDecoration: 'none',
            transition: 'border-color .12s',
          }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = active.color + '66')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = C.border)}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="t-headline" style={{ color: C.text, fontWeight: 700, flex: 1 }}>{r.title}</span>
              <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.05em', color: C.muted, border: `1px solid ${C.border2}`, borderRadius: 3, padding: '1px 5px', flexShrink: 0 }}>
                {KIND_LABEL[r.kind]}
              </span>
            </div>
            <div className="t-prose" style={{ fontSize: 11.5, marginTop: 5 }}>{r.desc}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', color: LEVEL_C[r.level] }}>{r.level.toUpperCase()}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: C.muted }}>{new URL(r.url).hostname.replace('www.', '')} ↗</span>
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
