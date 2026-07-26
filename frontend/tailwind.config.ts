import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        elevated: 'var(--elevated)',
        border: 'var(--border)',
        accent: 'var(--accent)',
        t1: 'var(--text-1)',
        t2: 'var(--text-2)',
        t3: 'var(--text-3)',
        success: 'var(--success)',
        warning: 'var(--warning)',
        danger: 'var(--danger)',
      },
    },
  },
  plugins: [],
} satisfies Config
