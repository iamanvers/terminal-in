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
  surfaceDeep: '#080808',   // deepest inset (table headers, sunken rows)
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
  onAccent: '#FFFFFF',   // text on a filled accent/teal button (active tabs, primary)

  // Primary accent — electric blue ramp (user-specified).
  accent:       '#0094FB',
  amber:        '#0094FB',   // legacy alias — hundreds of C.amber refs = accent
  accentBright: '#00B9FC',   // hover / emphasis
  accentMid:    '#006FF9',   // fills
  accentDeep:   '#004AF8',   // borders / selected fills
  accentInk:    '#0025F6',   // deepest — large fills only (poor small-text contrast)
  steel:        '#3A64B0',
  // Gold is now EXCLUSIVELY the warning color — warnings mean something again.
  warn:         '#FFB02E',

  // Semantic
  green:   '#2DBD80',
  red:     '#F2495C',
  blue:    '#3B8CFF',
  purple:  '#B07CC6',
  teal:    '#2FB8C6',

  // Regime extremes (market-state legend) — sanctioned palette members.
  strongBull: '#3FD487',
  strongBear: '#A13238',

  // Status aliases (agents page)
  run:     '#2DBD80',
  err:     '#F2495C',
  idle:    '#4A4F57',
} as const

export type Theme = typeof THEME
