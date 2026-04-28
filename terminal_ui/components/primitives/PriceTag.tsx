'use client'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'

type Props = { value: number; prev?: number; decimals?: number }

export default function PriceTag({ value, prev, decimals = 2 }: Props) {
  const [flash, setFlash] = useState<'pos' | 'neg' | null>(null)
  const prevRef = useRef(prev ?? value)

  useEffect(() => {
    if (value === prevRef.current) return
    setFlash(value > prevRef.current ? 'pos' : 'neg')
    prevRef.current = value
    const t = setTimeout(() => setFlash(null), 400)
    return () => clearTimeout(t)
  }, [value])

  const up = value >= (prev ?? value)
  return (
    <span
      className={clsx(
        'font-mono tabular-nums px-1 rounded-sm',
        flash === 'pos' && 'flash-pos',
        flash === 'neg' && 'flash-neg',
        up ? 'text-pos' : 'text-neg',
      )}
    >
      {value.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
    </span>
  )
}
