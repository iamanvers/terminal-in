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

type Toast = {
  id: number
  kind: 'trade' | 'reject' | 'news' | 'risk' | 'planner' | 'error'
  title: string
  body: string
  ts: number
}

const KIND_STYLE: Record<Toast['kind'], { color: string; icon: string }> = {
  trade:   { color: '#22C55E', icon: '◉' },
  reject:  { color: '#EAB308', icon: '⊘' },
  news:    { color: '#38BDF8', icon: '▣' },
  risk:    { color: '#EF4444', icon: '⚠' },
  planner: { color: '#F7931E', icon: '⚖' },
  error:   { color: '#EF4444', icon: '✕' },
}

let _nextId = 1

function ToastCard({ t, onClose }: { t: Toast; onClose: (id: number) => void }) {
  const s = KIND_STYLE[t.kind]
  return (
    <div className="fade-up" style={{
      width: 320, background: '#101010', border: '1px solid #242424',
      borderLeft: `3px solid ${s.color}`, borderRadius: 5, overflow: 'hidden',
      boxShadow: '0 6px 24px rgba(0,0,0,.55)', pointerEvents: 'auto',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 9, padding: '9px 10px 7px' }}>
        <span style={{ color: s.color, fontSize: 12, lineHeight: '14px', flexShrink: 0 }}>{s.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#E4E4E4', letterSpacing: '.04em' }}>{t.title}</div>
          {t.body && <div style={{ fontSize: 10, color: '#9A9A9A', marginTop: 2, lineHeight: 1.45, overflowWrap: 'break-word' }}>{t.body}</div>}
        </div>
        <button onClick={() => onClose(t.id)} aria-label="dismiss" style={{
          background: 'none', border: 'none', color: '#5C5C5C', cursor: 'pointer',
          fontSize: 11, lineHeight: '14px', padding: 0, flexShrink: 0,
        }}
          onMouseEnter={e => (e.currentTarget.style.color = '#E4E4E4')}
          onMouseLeave={e => (e.currentTarget.style.color = '#5C5C5C')}
        >✕</button>
      </div>
      {/* TTL progress bar */}
      <div style={{ height: 2, background: '#1A1A1A' }}>
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
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const close = useCallback((id: number) => {
    setToasts(ts => ts.filter(t => t.id !== id))
    const tm = timers.current.get(id)
    if (tm) { clearTimeout(tm); timers.current.delete(id) }
  }, [])

  const push = useCallback((kind: Toast['kind'], title: string, body = '') => {
    const id = _nextId++
    setToasts(ts => [...ts, { id, kind, title, body, ts: Date.now() }].slice(-MAX_TOASTS))
    timers.current.set(id, setTimeout(() => close(id), TOAST_TTL_MS))
  }, [close])

  useEffect(() => {
    const s = getSocket()
    type P = Record<string, unknown>
    const num = (v: unknown) => (typeof v === 'number' ? v : 0)
    const str = (v: unknown) => (v == null ? '' : String(v))

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

  useEffect(() => () => { timers.current.forEach(clearTimeout) }, [])

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
