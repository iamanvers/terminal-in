/**
 * THE design system palette — single source of truth.
 *
 * Every page imports this instead of defining its own `const C`. Values
 * mirror the CSS custom properties in styles/globals.css — change together.
 *
 * Direction: cool steel dark. Neutral-cool near-blacks, a DEEP MATTE STEEL
 * BLUE accent (flat — no gradients, no "reflection"), softened semantic
 * green/red, blue-grey text whites. Georgia carries display type;
 * JetBrains Mono carries data. True amber survives only as the warn color.
 */

export const THEME = {
  // Surfaces (darkest → lightest)
  bg:      '#0A0B0D',
  panel:   '#0F1114',
  card:    '#14161A',

  // Borders
  border:  '#20242B',
  border2: '#2B303A',

  // Text hierarchy (cool whites)
  text:    '#E6E9ED',
  sub:     '#9BA3AD',
  muted:   '#5F6772',
  dim:     '#3C424B',

  // Accent — deep matte steel blue.
  accent:  '#4E80B4',
  // `amber` is a legacy alias for the accent (hundreds of C.amber refs
  // predate the blue accent). For a true amber, use `warn`.
  amber:   '#4E80B4',
  warn:    '#D9A23C',

  // Semantic
  green:   '#2FBF71',
  red:     '#E5484D',
  blue:    '#4CA8E8',
  purple:  '#B07CC6',
  teal:    '#2FB8C6',

  // Status aliases (agents page)
  run:     '#2FBF71',
  err:     '#E5484D',
  idle:    '#3C424B',
} as const

export type Theme = typeof THEME
