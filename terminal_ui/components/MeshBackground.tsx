'use client'
// Dot-matrix mesh — an embossed grid behind every pane.
// Dots never move or scatter: each one is a tiny punched stud (highlight
// face over a south-east shadow — light source top-left) so the field
// reads as texture pressed into the surface. The cursor carries a soft
// lamp: nearby studs catch the accent light and feel raised, then settle
// back. The resting field is pre-rendered once and blitted; only the
// dots inside the lamp radius are repainted per frame.
// Pure canvas + rAF, pointer-events none, honors prefers-reduced-motion,
// pauses when the tab is hidden.
import React, { useEffect, useRef } from 'react'

const SPACING = 26            // px between dots (dense matrix, like perforated metal)
const RADIUS = 220            // cursor lamp radius
const DOT = 1.4               // dot size (never changes — embossed, not animated)
const BASE_LIGHT = 0.085      // resting highlight strength
const BASE_SHADOW = 0.5       // resting shadow strength (emboss depth)
const ACCENT = '0, 148, 251'  // #0094FB
const STEEL = '174, 187, 204' // cool grey-blue for the resting studs

export default function MeshBackground() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let w = 0, h = 0, cols = 0, rows = 0, dpr = 1
    let raf = 0
    let field: HTMLCanvasElement | null = null   // pre-rendered resting grid
    // the lamp eases toward the pointer — light glides, dots stay put
    const mouse = { x: -9999, y: -9999 }
    const lamp = { x: -9999, y: -9999 }

    const stud = (c: CanvasRenderingContext2D, x: number, y: number, face: string) => {
      c.fillStyle = `rgba(0, 0, 0, ${BASE_SHADOW})`
      c.fillRect(x - DOT / 2 + 0.7, y - DOT / 2 + 0.7, DOT, DOT)
      c.fillStyle = face
      c.fillRect(x - DOT / 2, y - DOT / 2, DOT, DOT)
    }

    const renderField = () => {
      field = document.createElement('canvas')
      field.width = w * dpr; field.height = h * dpr
      const fc = field.getContext('2d')!
      fc.setTransform(dpr, 0, 0, dpr, 0, 0)
      const rest = `rgba(${STEEL}, ${BASE_LIGHT})`
      for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++)
        stud(fc, i * SPACING, j * SPACING, rest)
    }

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = window.innerWidth; h = window.innerHeight
      canvas.width = w * dpr; canvas.height = h * dpr
      canvas.style.width = `${w}px`; canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      cols = Math.ceil(w / SPACING) + 1
      rows = Math.ceil(h / SPACING) + 1
      renderField()
    }

    const blitField = () => {
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      if (field) ctx.drawImage(field, 0, 0)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const onMove = (e: PointerEvent) => { mouse.x = e.clientX; mouse.y = e.clientY }
    const onLeave = () => { mouse.x = -9999; mouse.y = -9999 }

    const draw = () => {
      blitField()
      if (mouse.x < -999) { lamp.x = -9999; lamp.y = -9999 }
      else { lamp.x += (mouse.x - lamp.x) * 0.22; lamp.y += (mouse.y - lamp.y) * 0.22 }

      if (lamp.x > -999) {
        // soft ambient halo under the lamp — reads instantly, dots stay put
        const halo = ctx.createRadialGradient(lamp.x, lamp.y, 0, lamp.x, lamp.y, RADIUS)
        halo.addColorStop(0, `rgba(${ACCENT}, 0.085)`)
        halo.addColorStop(0.55, `rgba(${ACCENT}, 0.03)`)
        halo.addColorStop(1, `rgba(${ACCENT}, 0)`)
        ctx.fillStyle = halo
        ctx.fillRect(lamp.x - RADIUS, lamp.y - RADIUS, RADIUS * 2, RADIUS * 2)

        const r2 = RADIUS * RADIUS
        const i0 = Math.max(0, Math.floor((lamp.x - RADIUS) / SPACING))
        const i1 = Math.min(cols - 1, Math.ceil((lamp.x + RADIUS) / SPACING))
        const j0 = Math.max(0, Math.floor((lamp.y - RADIUS) / SPACING))
        const j1 = Math.min(rows - 1, Math.ceil((lamp.y + RADIUS) / SPACING))
        for (let i = i0; i <= i1; i++) {
          const x = i * SPACING
          for (let j = j0; j <= j1; j++) {
            const y = j * SPACING
            const dx = x - lamp.x, dy = y - lamp.y
            const d2 = dx * dx + dy * dy
            if (d2 >= r2) continue
            const t = 1 - Math.sqrt(d2) / RADIUS
            const p = t * t                       // smooth lamp falloff
            // deeper shadow under lit studs — emboss depth grows with light
            ctx.fillStyle = `rgba(0, 0, 0, ${Math.min(0.85, BASE_SHADOW + p * 0.35)})`
            ctx.fillRect(x - DOT / 2 + 0.8, y - DOT / 2 + 0.8, DOT, DOT)
            // accent-lit face over the same fixed footprint — no movement
            ctx.fillStyle = `rgba(${ACCENT}, ${Math.min(1, BASE_LIGHT + p * 0.95)})`
            ctx.fillRect(x - DOT / 2, y - DOT / 2, DOT, DOT)
            // specular catch on the brightest studs — the raised feel
            if (p > 0.12) {
              ctx.fillStyle = `rgba(255, 255, 255, ${Math.min(0.65, p * 0.6)})`
              ctx.fillRect(x - DOT / 2 - 0.5, y - DOT / 2 - 0.5, 1.1, 1.1)
            }
          }
        }
      }
      raf = requestAnimationFrame(draw)
    }

    const onVis = () => {
      cancelAnimationFrame(raf)
      if (!document.hidden && !reduced) raf = requestAnimationFrame(draw)
    }

    resize()
    if (reduced) {
      // static embossed field only — no lamp, no animation loop
      blitField()
      const onResize = () => { resize(); blitField() }
      window.addEventListener('resize', onResize)
      return () => window.removeEventListener('resize', onResize)
    }
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
