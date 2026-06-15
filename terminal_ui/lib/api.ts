const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json()
}

export type PortfolioSummary = {
  equity: number
  daily_pnl: number
  daily_trades: number
  drawdown: number
  peak_equity: number
  open_positions: number
  india_vix: number
}

export type Position = {
  trade_id: string
  strategy_id: string
  instrument_id: number
  side: 'BUY' | 'SELL'
  quantity: number
  entry_price: number
  stop_loss: number
  target: number
  opened_at: string
  regime: string
}

export type Scorecard = {
  strategy_id: string
  total_trades: number
  wins: number
  losses: number
  win_rate: number
  bayesian_wr: number
  expectancy: number
  total_pnl: number
  avg_win: number
  avg_loss: number
}

export type RegimeState = {
  regime: string
  confidence: number
  india_vix: number
  size_multiplier: number
  ts: string
}

export type NewsItem = {
  id: number
  published_at: number
  headline: string
  source: string
  url: string | null
  sentiment: 'positive' | 'negative' | 'neutral'
  score: number
  impact: 'high' | 'medium' | 'low'
  instruments: string[]
}

export type CalendarEvent = {
  date: string
  event: string
  mask: number
}

export type Trade = {
  trade_id: string
  strategy_id: string
  instrument_token: number
  side: 'BUY' | 'SELL'
  entry_price: number
  entry_time: number
  exit_price?: number
  exit_time?: number
  quantity: number
  net_pnl?: number
  exit_reason?: string
  stop_loss?: number
  target?: number
  regime_at_entry?: string
  confidence?: number
}

export type TradeStats = {
  total_trades: number
  wins: number
  losses: number
  win_rate: number
  total_pnl: number
  avg_win: number
  avg_loss: number
  best_trade_pnl: number
  worst_trade_pnl: number
  today_trades: number
  today_pnl: number
  by_strategy: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }>
}

export type Instrument = {
  symbol: string
  token: number
  type: string
}

export type SignalRec = {
  decision_id: string
  signal_id: string
  strategy_id: string
  instrument_token: number
  symbol: string | null
  approved: number   // 0 | 1
  reason: string | null
  decided_at: number
  side: 'BUY' | 'SELL' | null
  confidence: number | null
  regime: string | null
  regime_confidence: number | null
  trigger_rule: string | null
  trade_id: string | null
  trade_pnl: number | null
  fill_price: number | null
}

export type GlobalQuote = {
  label: string
  symbol: string
  category: 'global' | 'fx' | 'commod' | 'risk'
  price: number
  change: number
  updated: number
}

export type ChatResponse = {
  message: string
  type: string
  finbert?: { sentiment: string; score: number }
  override?: Record<string, unknown>
}

export type LearnerParams = {
  strategy_id: string
  min_confidence: number
  sl_multiplier: number
  target_multiplier: number
  kelly_fraction: number
  bayes_wr: number
  n_trades: number
  updated_at: number
}

export type JournalEntry = {
  journal_id: string
  trade_id: string
  entry_reason: string | null
  exit_reason: string | null
  strategy_rationale: string | null
  manual_notes: string | null
  lesson: string | null
  rating: number | null
  review_status: string | null
  created_at: string | null
  // joined from trades
  strategy_id: string | null
  instrument_token: number | null
  side: 'BUY' | 'SELL' | null
  entry_price: number | null
  net_pnl: number | null
}

export type AgentState = {
  agent_id: string
  agent_type: 'strategy' | 'orchestrator' | 'system'
  description: string
  status: 'running' | 'paused' | 'error' | 'idle'
  last_heartbeat: number
  heartbeat_age_s: number
  last_eval_ts: number
  last_signal_ts: number
  eval_count: number
  signal_count: number
  confidence_threshold: number
  last_error: string
}

export type KillSwitchState = {
  global_pause: boolean
  blocked_tokens: number[]
  auto_trade?: boolean
}

export type AuditEntry = {
  ts: number
  action: string
  detail: string
}

export type DecisionRecord = {
  decision_id: string
  signal_id: string
  strategy_id: string
  instrument_token: number
  approved: number        // 0 | 1
  reason: string | null
  decided_at: number
  daily_pnl_at_decision: number | null
  equity_at_decision: number | null
  // joined from signal_lineage
  side: 'BUY' | 'SELL' | null
  confidence: number | null
  regime: string | null
  regime_confidence: number | null
  trigger_rule: string | null
  trade_id: string | null
  trade_pnl: number | null
  fill_price: number | null
}

export type SignalLineage = {
  lineage_id: string
  signal_id: string
  strategy_id: string
  instrument_token: number
  side: 'BUY' | 'SELL' | null
  generated_at: number
  regime: string | null
  regime_confidence: number | null
  india_vix: number | null
  indicators: Record<string, number> | null
  trigger_rule: string | null
  confidence: number | null
  risk_approved: number
  risk_checks: Record<string, boolean> | null
  risk_reason: string | null
  // fill / close outcome
  fill_price: number | null
  trade_id: string | null
  trade_pnl: number | null
  trade_exit_reason: string | null
  trade_closed_at: number | null
  // joined trade record (optional)
  trade?: {
    entry_price: number | null
    exit_price: number | null
    net_pnl: number | null
    exit_reason: string | null
    side: string | null
    quantity: number | null
  }
}

export type EventRecord = {
  ts: number
  topic: string
  severity: 'info' | 'success' | 'warn' | 'critical'
  summary: string
  payload: Record<string, unknown>
}

export type SystemHealth = {
  healthy: number
  errored: number
  paused: number
  stale: number
  total: number
  health_pct: number
  global_pause: boolean
}

export type SettlementEvent = {
  date: string
  positions_closed?: number
  equity?: number
  daily_pnl?: number
}

export type OrchestratorResult = {
  symbol: string
  token: number
  price: number
  regime: string
  side: 'BUY' | 'SELL' | 'NEUTRAL' | 'SKIP'
  verdict: string
  confidence: number
  ev: number
  rsi: number
  ret_20d: number
  suggested_sl: number
  suggested_target: number
  atr14?: number
  rr?: number
  vol_factor?: number
  summary: string
  lenses: Array<{ strategy: string; side: string; confidence: number; detail: string }>
}

export type OrchestratorState = {
  scan_count: number
  last_scan_ts: number
  results: OrchestratorResult[]
}

export type PlannerVerdictItem = {
  symbol: string
  side: 'BUY' | 'SELL' | null
  action: 'approve' | 'reject'
  size_factor: number
  reason: string
  ev: number | null
}

export type PlannerVerdict = {
  scan_id: number
  ts: number
  mode: 'llm' | 'degraded' | 'off' | 'idle'
  model: string | null
  latency_ms: number
  fired: number
  verdicts: PlannerVerdictItem[]
}

export type PlannerState = {
  mode: 'llm' | 'degraded' | 'off' | 'idle'
  model: string
  plan_count: number
  last_latency_ms: number | null
  last_verdict: PlannerVerdict | Record<string, never>
}

export type AgentDecision = {
  decision_id: string
  scan_id: number
  decided_at: number
  instrument_token: number
  symbol: string
  side: string
  ev: number | null
  confidence: number | null
  persistence: number | null
  price_at_decision: number | null
  regime: string | null
  india_vix: number | null
  planner_action: 'approve' | 'reject' | 'filtered' | 'fired'
  planner_reason: string | null
  size_factor: number
  planner_mode: 'llm' | 'degraded' | 'off'
  llm_latency_ms: number | null
  signal_id: string | null
  hindsight_at: number | null
  hindsight_ret_pct: number | null
  hindsight_outcome: 'would_win' | 'would_lose' | 'flat' | 'actual_win' | 'actual_loss' | null
  lenses?: string[]
}

export type SupervisorState = {
  suppressed_lenses: Record<string, number>   // lens → seconds remaining
  lens_loss_streaks: Record<string, number>
  consec_losses: number
  throttle_level: number
}

export type BackendHealth = {
  status: 'ok' | 'degraded'
  degraded: string[]
  regime_mode: 'hmm' | 'heuristic'
  sentiment: { mode: string; available: boolean; loaded: boolean }
  ollama_online: boolean
  last_daily_bar: string | null
}

export type TrainingRun = {
  run_id: string
  started_at: number
  finished_at: number | null
  status: string
  max_steps: number | null
  dataset_samples: number | null
  dataset_counts?: Record<string, number>
  initial_loss: number | null
  final_loss: number | null
  trained_steps: number | null
  epochs: number | null
  adapter_dir: string | null
  error: string | null
}

export type TrainingStatus = {
  state: 'idle' | 'building_dataset' | 'training' | 'collecting' | 'completed' | 'failed' | 'unavailable'
  current_run: Partial<TrainingRun> & { dataset_counts?: Record<string, number> } | null
}

export type TrainingProgress = {
  active: boolean
  run_id?: string
  global_step?: number
  max_steps?: number | null
  elapsed?: string | null
  eta?: string | null
  sec_per_step?: number | null
  loss?: number | null
  losses?: number[]
  updated_ms?: number
}

export type AgentQueryResponse = {
  answer: string
  tool_calls: Array<{ tool: string; args: Record<string, unknown>; result: unknown }>
  model: string
  online: boolean
}

export type OllamaStatus = {
  online: boolean
  model: string
  host: string
}

export type NSESymbol = {
  symbol: string
  name: string
  series: string
  yf_symbol: string
}

// ── Backtest (PRD P2) ─────────────────────────────────────────────────────
export type BacktestStat = {
  n: number
  win_rate?: number
  total_pnl?: number
  avg_pnl?: number
}

export type BacktestTrade = {
  symbol: string
  lens: string
  side: string
  regime: string
  entry_date: string
  exit_date: string
  entry: number
  exit: number
  ev: number
  exit_reason: string
  pnl: number
  judge?: 'llm' | 'degraded'
  size_factor?: number
}

export type BacktestPlanner = {
  mode: 'degraded' | 'llm'
  ollama_available: boolean
  llm_batches: number
  degraded_batches: number
  llm_budget: number
}

export type BacktestResult = {
  ts: number
  days: number
  engine: string
  capital: number
  final_equity: number
  return_pct: number
  max_drawdown_pct: number
  sharpe: number
  trades: BacktestStat
  per_lens: Record<string, BacktestStat>
  per_regime: Record<string, BacktestStat>
  per_judge?: Record<string, BacktestStat>
  planner?: BacktestPlanner
  regime_days: Record<string, number>
  walk_forward_years: Record<string, BacktestStat>
  equity_curve: { date: string; equity: number }[]
  recent_trades: BacktestTrade[]
  symbols_tested: number
}

export type BacktestRunStatus = {
  active: boolean
  error: string | null
  started_ms: number | null
  params: { days: number; symbols: string[] | null; planner?: string } | null
  result: BacktestResult | null
}

export type BacktestLatest = { available: boolean; error?: string } & Partial<BacktestResult>

// ── F&O (PRD P2) ──────────────────────────────────────────────────────────
export type FnOLeg = {
  premium: number; delta: number; gamma: number; theta: number; vega: number
  theoretical: boolean; token: number
}
export type FnOChainRow = {
  strike: number; is_atm: boolean; moneyness: 'ATM' | 'ITM' | 'OTM'
  CE: FnOLeg; PE: FnOLeg
  oi: number | null; iv_real: number | null; volume: number | null
}
export type FnOExpiry = { date: string; kind: 'weekly' | 'monthly' }
export type FnOChain = {
  available?: boolean; error?: string; kind?: 'index' | 'stock'
  underlying: string; underlying_symbol: string; spot: number; atm_strike: number
  expiry: string; t_years: number; iv_used_pct: number; iv_source: string
  lot_size: number; strike_interval: number; rows: FnOChainRow[]
  theoretical: boolean; note: string
  spot_source?: string; vix_source?: string; expiries?: FnOExpiry[]
}
export type FnOUnderlying = {
  label: string; symbol: string; token: number; lot_size: number
  kind: 'index' | 'stock'
  strike_interval: number; spot: number; spot_source: string; weekly: boolean
}
export type FnOPosition = {
  trade_id: string; tradingsymbol: string; underlying: string
  opt_type: string; strike: number; expiry: string; lot_size: number; lots: number
  side: string; quantity: number; entry_price: number; margin: number
  mark: number; unrealized: number; spot: number; theoretical: boolean
  delta?: number; theta?: number; vega?: number; gamma_2pct?: number
}
export type FnOGreeks = {
  net_delta: number; net_delta_notional: number; net_gamma_2pct: number
  net_vega: number; net_theta: number; delta_pct_equity: number | null
}

// ── Trade execution → settlement pipeline ─────────────────────────────────
export type PipelineItem = {
  segment: 'EQ' | 'FNO'; symbol: string; strategy: string; side: string
  qty: number | null; entry: number | null; exit: number | null; pnl: number | null
  stage: 'rejected' | 'open' | 'closed' | 'settled'; exit_reason: string | null
  opened_at: number | null; closed_at: number | null; trade_id: string | null
}
export type TradePipeline = {
  funnel: { signaled: number; approved: number; rejected: number; open: number; closed: number }
  items: PipelineItem[]
}

export const api = {
  portfolio: ()           => get<PortfolioSummary>('/portfolio/summary'),
  positions: ()           => get<Position[]>('/portfolio/positions'),
  scorecards: ()          => get<Scorecard[]>('/strategies/scorecards'),
  allocations: ()         => get<Record<string, number>>('/strategies/allocations'),
  regime: ()              => get<RegimeState>('/market/regime'),
  allTicks: ()            => get<Record<string, Record<string, number>>>('/market/ticks'),
  lastCloses: ()          => get<Record<string, { close: number; date: string }>>('/market/closes'),
  news: (limit = 30)      => get<NewsItem[]>(`/market/news?limit=${limit}`),
  events: ()              => get<CalendarEvent[]>('/risk/events'),
  trades: (limit = 100)   => get<Trade[]>(`/trades/?limit=${limit}`),
  tradesClosed: (limit = 50) => get<Trade[]>(`/trades/closed?limit=${limit}`),
  tradePipeline: (limit = 40) => get<TradePipeline>(`/trades/pipeline?limit=${limit}`),
  tradeStats: ()          => get<TradeStats>('/trades/stats'),
  instruments: ()         => get<Instrument[]>('/market/instruments'),
  manualOrder: (order: { symbol: string; side: 'BUY' | 'SELL'; quantity: number; stop_loss?: number; target?: number; limit_price?: number }) =>
    fetch(`${BASE}/trades/manual`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(order),
    }).then(r => r.json()),
  closePosition: (tradeId: string) =>
    fetch(`${BASE}/trades/${tradeId}/close`, { method: 'POST' }).then(r => r.json()),
  signals: (limit = 40) => get<SignalRec[]>(`/trades/signals?limit=${limit}`),
  riskStats: ()           => get<Record<string, number>>('/risk/stats'),
  ohlcv: (sym: string, tf = '5m', limit = 200) =>
    get<Record<string, number>[]>(`/market/ohlcv/${sym}?tf=${tf}&limit=${limit}`),
  globalQuotes: ()        => get<GlobalQuote[]>('/market/global'),
  globalHistory: (symbol: string) => get<Record<string, number | string>[]>(`/market/global_history?symbol=${encodeURIComponent(symbol)}`),
  analyse: (symbol: string) => get<Record<string, unknown>>(`/strategies/analyse/${encodeURIComponent(symbol)}`),
  learnerParams: () => get<LearnerParams[]>('/strategies/learner_params'),
  portfolioSnapshots: (limit = 90) => get<Record<string, number>[]>(`/portfolio/snapshots?limit=${limit}`),
  orchestratorState: () => get<OrchestratorState>('/strategies/orchestrator'),
  orchestratorScan: () =>
    fetch(`${BASE}/strategies/orchestrator/scan`, { method: 'POST' }).then(r => r.json()),
  journal: (limit = 50) => get<JournalEntry[]>(`/trades/journal?limit=${limit}`),
  agents: () => get<AgentState[]>('/agents/'),
  agentPause: (id: string) =>
    fetch(`${BASE}/agents/${id}/pause`, { method: 'POST' }).then(r => r.json()),
  agentResume: (id: string) =>
    fetch(`${BASE}/agents/${id}/resume`, { method: 'POST' }).then(r => r.json()),
  agentForceEval: (id: string) =>
    fetch(`${BASE}/agents/${id}/force-eval`, { method: 'POST' }).then(r => r.json()),
  agentSetThreshold: (id: string, threshold: number) =>
    fetch(`${BASE}/agents/${id}/threshold`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ threshold }),
    }).then(r => r.json()),
  riskState: () => get<KillSwitchState>('/agents/risk/state'),
  setAutoTrade: (on: boolean) =>
    fetch(`${BASE}/agents/risk/auto-trade`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on }),
    }).then(r => r.json()) as Promise<{ ok: boolean; auto_trade: boolean }>,
  riskGlobalPause: (reason = 'manual') =>
    fetch(`${BASE}/agents/risk/global-pause`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }).then(r => r.json()),
  riskGlobalResume: (reason = 'manual') =>
    fetch(`${BASE}/agents/risk/global-resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }).then(r => r.json()),
  riskKillAll: () =>
    fetch(`${BASE}/agents/risk/kill-all`, { method: 'POST' }).then(r => r.json()),
  riskBlockSymbol: (token: number, reason = 'manual') =>
    fetch(`${BASE}/agents/risk/block-symbol`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, reason }),
    }).then(r => r.json()),
  riskUnblockSymbol: (token: number) =>
    fetch(`${BASE}/agents/risk/unblock-symbol`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }).then(r => r.json()),
  agentAudit: (limit = 100) => get<AuditEntry[]>(`/agents/audit?limit=${limit}`),
  agentHealth: () => get<SystemHealth>('/agents/health'),
  plannerState: () => get<PlannerState>('/agents/planner/state'),
  plannerDecisions: (limit = 50) => get<AgentDecision[]>(`/agents/planner/decisions?limit=${limit}`),
  supervisorState: () => get<SupervisorState>('/agents/supervisor/state'),
  backendHealth: () => get<BackendHealth>('/health'),
  trainingStatus: () => get<TrainingStatus>('/training/status'),
  trainingProgress: () => get<TrainingProgress>('/training/progress'),
  trainingRuns: (limit = 20) => get<TrainingRun[]>(`/training/runs?limit=${limit}`),
  trainingDeploy: (runId: string) =>
    fetch(`${BASE}/training/deploy`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: runId }),
    }).then(r => r.json()),
  trainingStart: (maxSteps = -1) =>
    fetch(`${BASE}/training/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_steps: maxSteps }),
    }).then(r => r.json()),
  trainingStop: () =>
    fetch(`${BASE}/training/stop`, { method: 'POST' }).then(r => r.json()),
  decisions: (limit = 60, strategyId?: string) =>
    get<DecisionRecord[]>(`/agents/decisions?limit=${limit}${strategyId ? `&strategy_id=${strategyId}` : ''}`),
  lineage: (signalId: string) => get<SignalLineage>(`/agents/lineage/${signalId}`),
  busEvents: (limit = 200) => get<EventRecord[]>(`/agents/events?limit=${limit}`),
  chat: (message: string, context?: Record<string, unknown>) =>
    fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, context }),
    }).then(r => r.json()) as Promise<ChatResponse>,
  agentQuery: (query: string, history?: Array<{ role: string; content: string }>) =>
    fetch(`${BASE}/agents/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, history }),
    }).then(r => r.json()) as Promise<AgentQueryResponse>,
  ollamaStatus: () => get<OllamaStatus>('/agents/ollama/status'),
  fnoUnderlyings: () => get<{ underlyings: FnOUnderlying[]; fut_margin_band: [number, number] }>('/fno/underlyings'),
  fnoExpiries: (u: string) => get<{ underlying: string; expiries: FnOExpiry[] }>(`/fno/expiries?underlying=${encodeURIComponent(u)}`),
  fnoChain: (u: string, expiry?: string, strikes = 10) =>
    get<FnOChain>(`/fno/chain?underlying=${encodeURIComponent(u)}&strikes=${strikes}${expiry ? `&expiry=${expiry}` : ''}`),
  fnoOrder: (order: { underlying: string; expiry: string; strike: number; opt_type: string; side: string; lots: number; sl_premium?: number; target_premium?: number }) =>
    fetch(`${BASE}/fno/order`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(order),
    }).then(r => r.json()) as Promise<{ ok: boolean; error?: string; trade_id?: string; premium?: number; qty?: number; margin?: number; tradingsymbol?: string }>,
  fnoPositions: () => get<{ positions: FnOPosition[]; available: boolean; count: number; unrealized: number; margin_used: number; greeks?: FnOGreeks }>('/fno/positions'),
  fnoClosePosition: (tradeId: string) =>
    fetch(`${BASE}/fno/close`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_id: tradeId }),
    }).then(r => r.json()) as Promise<{ ok: boolean; error?: string }>,
  backtestLatest: () => get<BacktestLatest>('/backtest/latest'),
  backtestStatus: () => get<BacktestRunStatus>('/backtest/run'),
  backtestRun: (days = 730, planner: 'degraded' | 'llm' = 'degraded', symbols?: string[]) =>
    fetch(`${BASE}/backtest/run`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days, planner, symbols }),
    }).then(r => r.json()) as Promise<{ ok: boolean; error?: string; params?: unknown }>,
  symbolSearch: (q: string, limit = 15) =>
    get<NSESymbol[]>(`/agents/symbols/search?q=${encodeURIComponent(q)}&limit=${limit}`),
}
