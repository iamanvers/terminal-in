'use client'
/**
 * Global toast notifications — bottom-right stack.
 *
 * Surfaces the events an operator must not miss: trade opened/closed,
 * order rejections, high-impact news, kill-switch / throttle changes,
 * planner approvals. Each toast lives 30s (progress bar) and can be
 * dismissed with ✕. Mounted once in the root layout.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { getSocket } from '@/lib/socket'

const TOAST_TTL_MS = 30_000
const MAX_TOASTS = 5

// Persistent "already shown" set for news headlines. The server replays recent
// events from its ring buffer when a client (re)connects after a backend
// restart — without this, every previously-seen news popup fires again. Keyed
// by a stable news id (url/id/headline) and persisted in localStorage.
const SEEN_NEWS_KEY = 'tin_seen_news'
const SEEN_NEWS_MAX = 800
function loadSeenNews(): Set<string> {
  if (typeof localStorage === 'undefined') return new Set()
  try { return new Set(JSON.parse(localStorage.getItem(SEEN_NEWS_KEY) || '[]')) } catch { return new Set() }
}
function persistSeenNews(set: Set<string>) {
  if (typeof localStorage === 'undefined') return
  try { localStorage.setItem(SEEN_NEWS_KEY, JSON.stringify([...set].slice(-SEEN_NEWS_MAX))) } catch { /* quota */ }
}

type Toast = {
  id: number
  kind: 'trade' | 'reject' | 'news' | 'risk' | 'planner' | 'error'
  title: string
  body: string
  ts: number
}

const KIND_STYLE: Record<Toast['kind'], { color: string; icon: string }> = {
  trade:   { color: '#2DBD80', icon: '◉' },
  reject:  { color: '#FFB02E', icon: '⊘' },
  news:    { color: '#3B8CFF', icon: '▣' },
  risk:    { color: '#F2495C', icon: '⚠' },
  planner: { color: '#0094FB', icon: '⚖' },
  error:   { color: '#F2495C', icon: '✕' },
}

let _nextId = 1

function ToastCard({ t, onClose }: { t: Toast; onClose: (id: number) => void }) {
  const s = KIND_STYLE[t.kind]
  return (
    <div className="fade-up" style={{
      width: 320, background: '#15171C', border: '1px solid #333841',
      borderLeft: `3px solid ${s.color}`, borderRadius: 5, overflow: 'hidden',
      boxShadow: '0 6px 24px rgba(0,0,0,.55)', pointerEvents: 'auto',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 9, padding: '9px 10px 7px' }}>
        <span style={{ color: s.color, fontSize: 12.5, lineHeight: '14px', flexShrink: 0 }}>{s.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: '#ECEEF1', letterSpacing: '.04em' }}>{t.title}</div>
          {t.body && <div style={{ fontSize: 10.5, color: '#AEB3BB', marginTop: 2, lineHeight: 1.45, overflowWrap: 'break-word' }}>{t.body}</div>}
        </div>
        <button onClick={() => onClose(t.id)} aria-label="dismiss" style={{
          background: 'none', border: 'none', color: '#71767F', cursor: 'pointer',
          fontSize: 11.5, lineHeight: '14px', padding: 0, flexShrink: 0,
        }}
          onMouseEnter={e => (e.currentTarget.style.color = '#ECEEF1')}
          onMouseLeave={e => (e.currentTarget.style.color = '#71767F')}
        >✕</button>
      </div>
      {/* TTL progress bar */}
      <div style={{ height: 2, background: '#23272E' }}>
        <div style={{
          height: '100%', background: `${s.color}88`, transformOrigin: 'left',
          animation: `toast-ttl ${TOAST_TTL_MS}ms linear forwards`,
        }} />
      </div>
    </div>
  )
}

export default function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seenNews = useRef<Set<string>>(new Set())
  const close = useCallback((id: number) => {
    setToasts(ts => ts.filter(t => t.id !== id))
  }, [])

  const push = useCallback((kind: Toast['kind'], title: string, body = '') => {
    // Hidden tab: timers are throttled, so toasts would pile up and replay
    // on return. The user can't see them anyway — drop instead of queueing.
    if (typeof document !== 'undefined' && document.hidden) return
    const id = _nextId++
    setToasts(ts => {
      // Dedupe: identical title+body refreshes the existing toast instead
      // of stacking a copy.
      if (ts.some(t => t.title === title && t.body === body)) return ts
      return [...ts, { id, kind, title, body, ts: Date.now() }].slice(-MAX_TOASTS)
    })
  }, [])

  useEffect(() => {
    const s = getSocket()
    type P = Record<string, unknown>
    const num = (v: unknown) => (typeof v === 'number' ? v : 0)
    const str = (v: unknown) => (v == null ? '' : String(v))
    seenNews.current = loadSeenNews()   // restore across reloads / restarts

    const onOpened = (p: P) =>
      push('trade', `TRADE OPENED — ${str(p.side)} ${str(p.tradingsymbol || p.instrument_token)}`,
        `qty ${str(p.quantity)} @ ₹${num(p.entry_price).toFixed(2)}`)
    const onClosed = (p: P) => {
      const pnl = num(p.pnl)
      push('trade', `TRADE CLOSED — ${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(0)}`,
        `${str(p.trade_id)} · ${str(p.exit_reason)}`)
    }
    const onRejected = (p: P) =>
      push('reject', 'ORDER REJECTED', `${str(p.strategy_id)} ${str(p.side)} — ${str(p.reason)}`)
    const onNews = (p: P) => {
      if (p.impact !== 'high') return   // only headline-worthy items
      const key = str(p.url || p.id || p.headline)
      if (!key || seenNews.current.has(key)) return   // already shown (even pre-restart)
      seenNews.current.add(key)
      persistSeenNews(seenNews.current)
      push('news', `HIGH IMPACT — ${str(p.sentiment).toUpperCase()}`, str(p.headline).slice(0, 140))
    }
    const onKill = (p: P) =>
      push('risk', p.paused ? 'KILL SWITCH ENGAGED' : 'KILL SWITCH RELEASED', str(p.reason))
    const onThrottle = (p: P) => {
      if (num(p.level) > 0) push('risk', `SUPERVISOR THROTTLE L${str(p.level)}`, str(p.reason))
    }
    const onVerdict = (p: P) => {
      const verdicts = (p.verdicts as Array<P> | undefined) ?? []
      const approved = verdicts.filter(v => v.action === 'approve')
      if (approved.length === 0) return
      push('planner', `PLANNER APPROVED ${approved.length} TRADE${approved.length > 1 ? 'S' : ''}`,
        approved.map(v => `${str(v.side)} ${str(v.symbol)}`).join(' · '))
    }
    const onError = (p: P) =>
      push('error', `SYSTEM ERROR [${str(p.source)}]`, str(p.message).slice(0, 140))

    s.on('trade_opened', onOpened)
    s.on('trade_closed', onClosed)
    s.on('order_rejected', onRejected)
    s.on('news_signal', onNews)
    s.on('kill_switch_global_pause', onKill)
    s.on('supervisor_throttle', onThrottle)
    s.on('planner_verdict', onVerdict)
    s.on('system_error', onError)
    return () => {
      s.off('trade_opened', onOpened)
      s.off('trade_closed', onClosed)
      s.off('order_rejected', onRejected)
      s.off('news_signal', onNews)
      s.off('kill_switch_global_pause', onKill)
      s.off('supervisor_throttle', onThrottle)
      s.off('planner_verdict', onVerdict)
      s.off('system_error', onError)
    }
  }, [push])

  // TTL enforcement by age sweep (robust across background-tab throttling)
  useEffect(() => {
    const t = setInterval(() => {
      setToasts(ts => {
        const now = Date.now()
        const live = ts.filter(x => now - x.ts < TOAST_TTL_MS)
        return live.length === ts.length ? ts : live
      })
    }, 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: '@keyframes toast-ttl { from { transform: scaleX(1) } to { transform: scaleX(0) } }' }} />
      <div style={{
        position: 'fixed', right: 14, bottom: 14, zIndex: 9999,
        display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
      }}>
        {toasts.map(t => <ToastCard key={t.id} t={t} onClose={close} />)}
      </div>
    </>
  )
}
