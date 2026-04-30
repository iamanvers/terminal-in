'use client'
import { useEffect, useRef, useState } from 'react'
import { getSocket } from '@/lib/socket'

export function useSocketEvent<T>(event: string, initial: T): T {
  const [data, setData] = useState<T>(initial)
  useEffect(() => {
    const socket = getSocket()
    const handler = (payload: T) => setData(payload)
    socket.on(event, handler)
    return () => { socket.off(event, handler) }
  }, [event])
  return data
}

// Appends to a capped list; newest first
export function useSocketList<T>(event: string, maxLen = 50): T[] {
  const [items, setItems] = useState<T[]>([])
  useEffect(() => {
    const socket = getSocket()
    const handler = (payload: T) =>
      setItems(prev => [payload, ...prev].slice(0, maxLen))
    socket.on(event, handler)
    return () => { socket.off(event, handler) }
  }, [event, maxLen])
  return items
}

// Tick map: token → last payload.
// Batches all incoming ticks within a 250ms window into a single state update
// to prevent one render per tick (18 tokens × 1Hz = 18 re-renders/s otherwise).
export function useTickMap(): Record<number, Record<string, number>> {
  const [ticks, setTicks] = useState<Record<number, Record<string, number>>>({})
  const pendingRef = useRef<Record<number, Record<string, number>>>({})
  const timerRef   = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const socket = getSocket()
    const handler = (payload: Record<string, number>) => {
      const token = payload.instrument_token
      if (!token) return
      pendingRef.current[token] = payload
      if (!timerRef.current) {
        timerRef.current = setTimeout(() => {
          const batch = pendingRef.current
          pendingRef.current = {}
          timerRef.current = null
          setTicks(prev => ({ ...prev, ...batch }))
        }, 250)
      }
    }
    socket.on('ticks', handler)
    return () => {
      socket.off('ticks', handler)
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
    }
  }, [])
  return ticks
}

export type ConnStatus = 'connected' | 'reconnecting' | 'disconnected'

export function useConnected(): boolean {
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    const socket = getSocket()
    const on  = () => setConnected(true)
    const off = () => setConnected(false)
    setConnected(socket.connected)
    socket.on('connect',    on)
    socket.on('disconnect', off)
    // Catch immediate connect if it fired before this effect ran
    if (socket.connected) setConnected(true)
    return () => { socket.off('connect', on); socket.off('disconnect', off) }
  }, [])
  return connected
}

export function useConnStatus(): ConnStatus {
  const [status, setStatus] = useState<ConnStatus>('reconnecting')
  useEffect(() => {
    const socket = getSocket()
    setStatus(socket.connected ? 'connected' : 'reconnecting')
    const onConnect   = () => setStatus('connected')
    const onDisconnect = () => setStatus('disconnected')
    const onAttempt   = () => setStatus('reconnecting')
    socket.on('connect',           onConnect)
    socket.on('disconnect',        onDisconnect)
    socket.on('reconnect_attempt', onAttempt)
    socket.on('reconnect',         onConnect)
    socket.on('reconnect_failed',  onDisconnect)
    return () => {
      socket.off('connect',           onConnect)
      socket.off('disconnect',        onDisconnect)
      socket.off('reconnect_attempt', onAttempt)
      socket.off('reconnect',         onConnect)
      socket.off('reconnect_failed',  onDisconnect)
    }
  }, [])
  return status
}
