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

// Tick map: token → last payload; merges on each update
export function useTickMap(): Record<number, Record<string, number>> {
  const [ticks, setTicks] = useState<Record<number, Record<string, number>>>({})
  useEffect(() => {
    const socket = getSocket()
    const handler = (payload: Record<string, number>) => {
      const token = payload.instrument_token
      if (!token) return
      setTicks(prev => ({ ...prev, [token]: payload }))
    }
    socket.on('ticks', handler)
    return () => { socket.off('ticks', handler) }
  }, [])
  return ticks
}

export function useConnected(): boolean {
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    const socket = getSocket()
    const on  = () => setConnected(true)
    const off = () => setConnected(false)
    setConnected(socket.connected)
    socket.on('connect', on)
    socket.on('disconnect', off)
    return () => { socket.off('connect', on); socket.off('disconnect', off) }
  }, [])
  return connected
}
