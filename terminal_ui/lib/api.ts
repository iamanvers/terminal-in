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
  exit_price?: number
  quantity: number
  net_pnl?: number
  exit_reason?: string
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

export const api = {
  portfolio: ()           => get<PortfolioSummary>('/portfolio/summary'),
  positions: ()           => get<Position[]>('/portfolio/positions'),
  scorecards: ()          => get<Scorecard[]>('/strategies/scorecards'),
  allocations: ()         => get<Record<string, number>>('/strategies/allocations'),
  regime: ()              => get<RegimeState>('/market/regime'),
  news: (limit = 30)      => get<NewsItem[]>(`/market/news?limit=${limit}`),
  events: ()              => get<CalendarEvent[]>('/risk/events'),
  trades: (limit = 100)   => get<Trade[]>(`/trades/?limit=${limit}`),
  riskStats: ()           => get<Record<string, number>>('/risk/stats'),
  ohlcv: (sym: string, tf = '5m', limit = 200) =>
    get<Record<string, number>[]>(`/market/ohlcv/${sym}?tf=${tf}&limit=${limit}`),
  globalQuotes: ()        => get<GlobalQuote[]>('/market/global'),
  globalHistory: (symbol: string) => get<Record<string, number | string>[]>(`/market/global_history?symbol=${encodeURIComponent(symbol)}`),
  analyse: (symbol: string) => get<Record<string, unknown>>(`/strategies/analyse/${encodeURIComponent(symbol)}`),
  chat: (message: string, context?: Record<string, unknown>) =>
    fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, context }),
    }).then(r => r.json()) as Promise<ChatResponse>,
}
