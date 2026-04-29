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

export type SettlementEvent = {
  date: string
  positions_closed?: number
  equity?: number
  daily_pnl?: number
}

export const api = {
  portfolio: ()           => get<PortfolioSummary>('/portfolio/summary'),
  positions: ()           => get<Position[]>('/portfolio/positions'),
  scorecards: ()          => get<Scorecard[]>('/strategies/scorecards'),
  allocations: ()         => get<Record<string, number>>('/strategies/allocations'),
  regime: ()              => get<RegimeState>('/market/regime'),
  news: (limit = 30)      => get<NewsItem[]>(`/market/news?limit=${limit}`),
  events: ()              => get<CalendarEvent[]>('/risk/events'),
  trades: (limit = 100)   => get<Trade[]>(`/trades/?limit=${limit}`),
  tradesClosed: (limit = 50) => get<Trade[]>(`/trades/closed?limit=${limit}`),
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
  chat: (message: string, context?: Record<string, unknown>) =>
    fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, context }),
    }).then(r => r.json()) as Promise<ChatResponse>,
}
