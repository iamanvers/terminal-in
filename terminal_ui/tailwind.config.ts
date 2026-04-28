import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './hooks/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:       '#0A0A0A',
        surface:  '#111111',
        border:   '#1E1E1E',
        accent:   '#F7931E',
        pos:      '#00C853',
        neg:      '#D32F2F',
        muted:    '#888888',
        dim:      '#444444',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
