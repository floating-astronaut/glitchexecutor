import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'g-bg':     '#0a0a0a',
        'g-card':   '#111318',
        'g-deep':   '#0d1117',
        'g-border': '#1e2330',
        'accent':   '#00ff88',
        'gold':     '#d4a843',
        'g-text':   '#c9d1d9',
        'g-muted':  '#6e7681',
        'g-dim':    '#484f58',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
