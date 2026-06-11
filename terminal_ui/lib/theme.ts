/**
 * THE design system palette — single source of truth.
 *
 * Every page imports this instead of defining its own `const C`. Values
 * mirror the CSS custom properties in styles/globals.css — change together.
 *
 * Direction: cool steel dark. Neutral-cool near-blacks, a DEEP MATTE STEEL
 * Source: the user's design file ("Terminal-IN Design System.dc.html").
 * Gold #FFB02E is the PRIMARY accent (the file commits to it); deep
 * metallic blue #3A64B0 is the SECONDARY (selection/info/links), flat —
 * no gradients. Geist Mono carries data, Geist the UI, Georgia display.
 */

export const THEME = {
  // Surfaces (darkest → lightest)
  bg:      '#0A0B0D',
  panel:   '#121419',
  card:    '#1C1F25',

  // Borders
  border:  '#23272E',
  border2: '#333841',

  // Text hierarchy (cool whites)
  text:    '#ECEEF1',
  sub:     '#AEB3BB',
  muted:   '#71767F',
  dim:     '#4A4F57',

  // Primary accent — gold (per the design file). `amber` = legacy alias.
  accent:  '#FFB02E',
  amber:   '#FFB02E',
  // Secondary accent — deep metallic blue, flat.
  steel:   '#3A64B0',
  warn:    '#FFB02E',

  // Semantic
  green:   '#2DBD80',
  red:     '#F2495C',
  blue:    '#3B8CFF',
  purple:  '#B07CC6',
  teal:    '#2FB8C6',

  // Status aliases (agents page)
  run:     '#2DBD80',
  err:     '#F2495C',
  idle:    '#4A4F57',
} as const

export type Theme = typeof THEME
