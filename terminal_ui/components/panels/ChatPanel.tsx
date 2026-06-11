'use client'
import { useEffect, useRef, useState, KeyboardEvent } from 'react'
import { api, type RegimeState, type PortfolioSummary, type ChatResponse } from '@/lib/api'
import { useSocketList, useSocketEvent } from '@/hooks/useSocket'

type SignalEntry = {
  strategy_id: string
  side: string
  instrument_id: number
  confidence: number
  regime: string
  stop_loss?: number
  target?: number
  ts?: number
}

type Message = {
  role: 'user' | 'assistant'
  text: string
  type?: string
  finbert?: { sentiment: string; score: number }
  ts: number
}

const SUGGESTIONS = [
  'What is the current market regime?',
  'Show best trade signals',
  'NIFTY analysis',
  'Portfolio status',
  'Increase stop loss by 10%',
  'Reduce position size by 20%',
]

const FINBERT_COLOR: Record<string, string> = {
  positive: '#2DBD80',
  negative: '#F2495C',
  neutral:  '#71767F',
}

export default function ChatPanel() {
  const [messages, setMessages]   = useState<Message[]>([])
  const [input, setInput]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [regime, setRegime]       = useState<RegimeState | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLInputElement>(null)

  const signals      = useSocketList<SignalEntry>('strategy_signal', 30)
  const regimeUpdate = useSocketEvent<RegimeState | null>('regime_update', null)
  const pnlUpdate    = useSocketEvent<Partial<PortfolioSummary> | null>('pnl_update', null)

  useEffect(() => {
    api.regime().then(setRegime).catch(() => {})
    api.portfolio().then(setPortfolio).catch(() => {})
  }, [])

  useEffect(() => {
    if (regimeUpdate) setRegime(regimeUpdate)
  }, [regimeUpdate])

  useEffect(() => {
    if (pnlUpdate) setPortfolio(prev => prev ? { ...prev, ...pnlUpdate } : prev)
  }, [pnlUpdate])

  // Scroll to bottom on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Welcome message on mount
  useEffect(() => {
    setMessages([{
      role: 'assistant',
      text: 'TERMINAL//IN Intelligence\n\nI know your current regime, active signals, and portfolio state. Ask me anything or send commands:\n  • "What is the current regime?"\n  • "NIFTY analysis"\n  • "Reduce position size by 20%"\n  • "Overweight RSI by 15%"',
      type: 'welcome',
      ts: Date.now(),
    }])
  }, [])

  const send = async (text: string) => {
    const msg = text.trim()
    if (!msg || loading) return
    setInput('')

    setMessages(prev => [...prev, { role: 'user', text: msg, ts: Date.now() }])
    setLoading(true)

    try {
      const context: Record<string, unknown> = {}
      if (signals.length) context.signals = signals.slice(0, 10)
      if (regime)        context.regime   = regime
      if (portfolio)     context.portfolio = portfolio

      const res: ChatResponse = await api.chat(msg, context)
      setMessages(prev => [...prev, {
        role:    'assistant',
        text:    res.message,
        type:    res.type,
        finbert: res.finbert,
        ts:      Date.now(),
      }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: 'Error: could not reach the intelligence backend. Check that the Flask server is running.',
        type: 'error',
        ts:   Date.now(),
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  return (
    <div className="panel h-full" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="panel-header justify-between">
        <span><span className="accent">▸</span> MARKET INTELLIGENCE</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {regime && (
            <span style={{ fontSize: 10, color: '#71767F' }}>
              {regime.regime?.toUpperCase()} · VIX {regime.india_vix?.toFixed(1)}
            </span>
          )}
          <span style={{ fontSize: 10, color: '#4A4F57', letterSpacing: '0.04em' }}>FinBERT</span>
        </div>
      </div>

      {/* Message history */}
      <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: '#333841 transparent', minHeight: 0 }}>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              padding: '8px 12px',
              borderBottom: '1px solid #111',
              background: m.role === 'user' ? '#121419' : 'transparent',
            }}
          >
            {m.role === 'user' ? (
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <span style={{ fontSize: 10.5, color: '#ECEEF1', background: '#23272E', border: '1px solid #4A4F57', borderRadius: 3, padding: '4px 8px', maxWidth: '85%' }}>
                  {m.text}
                </span>
              </div>
            ) : (
              <div>
                <pre style={{
                  margin: 0, fontSize: 10.5, color: '#CFD3D9', lineHeight: 1.55,
                  fontFamily: 'inherit', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  borderLeft: m.type === 'command_applied' ? '2px solid #0094FB'
                            : m.type === 'error' ? '2px solid #F2495C'
                            : m.type === 'welcome' ? '2px solid #0094FB'
                            : '2px solid #333841',
                  paddingLeft: 8,
                }}>
                  {m.text}
                </pre>
                {m.finbert && m.role === 'assistant' && m.type !== 'welcome' && (
                  <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ fontSize: 9.5, color: '#4A4F57' }}>FinBERT:</span>
                    <span style={{ fontSize: 9.5, color: FINBERT_COLOR[m.finbert.sentiment] ?? '#71767F' }}>
                      {m.finbert.sentiment} {(m.finbert.score * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ padding: '8px 12px' }}>
            <span style={{ fontSize: 10.5, color: '#71767F' }}>Analysing…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestion chips */}
      <div style={{ flexShrink: 0, padding: '6px 8px', borderTop: '1px solid #23272E', display: 'flex', gap: 4, flexWrap: 'wrap', background: '#0A0B0D' }}>
        {SUGGESTIONS.map((s, i) => (
          <button
            key={i}
            onClick={() => send(s)}
            style={{ fontSize: 9.5, padding: '2px 6px', background: '#23272E', border: '1px solid #4A4F57', borderRadius: 2, color: '#71767F', cursor: 'pointer', whiteSpace: 'nowrap' }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div style={{ flexShrink: 0, display: 'flex', gap: 6, padding: '6px 8px', borderTop: '1px solid #333841', background: '#121419' }}>
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask about market, signals, or issue override commands…"
          style={{
            flex: 1, background: '#23272E', border: '1px solid #4A4F57', borderRadius: 3,
            color: '#ECEEF1', fontSize: 10.5, padding: '5px 8px', outline: 'none',
            fontFamily: 'inherit',
          }}
        />
        <button
          onClick={() => send(input)}
          disabled={loading || !input.trim()}
          style={{
            padding: '4px 10px', fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
            background: input.trim() && !loading ? '#0094FB' : '#23272E',
            color: input.trim() && !loading ? '#000' : '#4A4F57',
            border: 'none', borderRadius: 3, cursor: input.trim() && !loading ? 'pointer' : 'default',
          }}
        >
          ASK
        </button>
      </div>
    </div>
  )
}
