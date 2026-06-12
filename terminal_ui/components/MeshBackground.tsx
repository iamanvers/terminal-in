'use client'
// Electric mesh — cursor-reactive background across the whole canvas.
// A fixed dot-grid behind every pane: near-invisible at rest, nodes and
// links energize in the accent blue around the pointer. Pure canvas +
// rAF, pointer-events none, honors prefers-reduced-motion, pauses when
// the tab is hidden. Panels keep their solid surfaces — the mesh lives
// in the page background and panel gutters.
import React, { useEffect, useRef } from 'react'

const SPACING = 42          // px between nodes
const RADIUS = 210          // cursor influence radius
const BASE_ALPHA = 0.09     // idle visibility
const ACCENT = '0, 148, 251'   // #0094FB

export default function MeshBackground() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let w = 0, h = 0, cols = 0, rows = 0
    let raf = 0
    const mouse = { x: -9999, y: -9999, vx: 0, vy: 0 }
    let energy = 0   // eases toward 1 while the cursor moves, decays at rest

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = window.innerWidth; h = window.innerHeight
      canvas.width = w * dpr; canvas.height = h * dpr
      canvas.style.width = `${w}px`; canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      cols = Math.ceil(w / SPACING) + 1
      rows = Math.ceil(h / SPACING) + 1
    }

    const onMove = (e: PointerEvent) => {
      mouse.vx = e.clientX - mouse.x; mouse.vy = e.clientY - mouse.y
      mouse.x = e.clientX; mouse.y = e.clientY
      energy = Math.min(1, energy + 0.18)
    }
    const onLeave = () => { mouse.x = -9999; mouse.y = -9999 }

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h)
      energy *= 0.96
      const r2 = RADIUS * RADIUS

      for (let i = 0; i < cols; i++) {
        for (let j = 0; j < rows; j++) {
          const gx = i * SPACING, gy = j * SPACING
          const dx = gx - mouse.x, dy = gy - mouse.y
          const d2 = dx * dx + dy * dy
          // proximity 0..1 with smooth falloff
          const p = d2 < r2 ? (1 - Math.sqrt(d2) / RADIUS) : 0
          // subtle breathing at idle + displacement away from the cursor
          const breathe = Math.sin(t / 1900 + (i * 7 + j * 13) * 0.7) * 0.5 + 0.5
          const push = p * 9 * (0.35 + 0.65 * energy)
          const x = gx + (d2 > 0 ? (dx / Math.sqrt(d2 + 1)) * push : 0)
          const y = gy + (d2 > 0 ? (dy / Math.sqrt(d2 + 1)) * push : 0)
          const a = BASE_ALPHA * (0.5 + 0.5 * breathe) + p * p * 0.85 * (0.45 + 0.55 * energy)

          if (p > 0.03) {
            // energized links to right + down neighbours
            ctx.strokeStyle = `rgba(${ACCENT}, ${Math.min(0.6, a * 0.65)})`
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(x, y); ctx.lineTo(gx + SPACING, gy)
            ctx.moveTo(x, y); ctx.lineTo(gx, gy + SPACING)
            ctx.stroke()
          }
          const s = 1.5 + p * 1.8   // nodes swell near the cursor
          ctx.fillStyle = `rgba(${ACCENT}, ${Math.min(0.9, a)})`
          ctx.fillRect(x - s / 2, y - s / 2, s, s)
        }
      }
      raf = requestAnimationFrame(draw)
    }

    const onVis = () => {
      cancelAnimationFrame(raf)
      if (!document.hidden) raf = requestAnimationFrame(draw)
    }

    resize()
    raf = requestAnimationFrame(draw)
    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', onMove, { passive: true })
    document.addEventListener('pointerleave', onLeave)
    document.addEventListener('visibilitychange', onVis)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerleave', onLeave)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <canvas
      ref={ref}
      aria-hidden
      style={{ position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none' }}
    />
  )
}
