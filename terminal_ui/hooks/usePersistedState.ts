'use client'
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

/**
 * useState that survives navigation + refresh by mirroring to localStorage.
 *
 * Why: each module is a separate Next route, so switching pages unmounts the
 * component and plain useState snaps back to its default. Tab selections,
 * toggles, filters, the chosen symbol/expiry/horizon etc. should persist for
 * the session — backend-derived data already does (it's re-fetched). Keys are
 * namespaced `tin.<area>.<thing>`; values JSON round-trip.
 *
 * SSR-safe: starts from `initial`, hydrates from storage on mount (so the
 * static export doesn't mismatch), then writes on every change.
 */
export function usePersistedState<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(initial)
  const hydrated = useRef(false)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(key)
      if (raw != null) setValue(JSON.parse(raw) as T)
    } catch { /* ignore corrupt/unavailable storage */ }
    hydrated.current = true
    // key is stable per call-site; intentional one-shot hydrate
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!hydrated.current) return
    try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* quota/private mode */ }
  }, [key, value])

  return [value, setValue]
}
