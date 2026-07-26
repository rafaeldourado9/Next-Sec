import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ThemeState {
  accentColor: string
  logoUrl: string | null
  systemName: string
  setTheme: (opts: { accentColor?: string; logoUrl?: string | null; systemName?: string }) => void
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      accentColor: import.meta.env.VITE_ACCENT_COLOR ?? '#3B82F6',
      logoUrl: null,
      systemName: import.meta.env.VITE_APP_NAME ?? 'VMS',

      setTheme: ({ accentColor, logoUrl, systemName }) => {
        set((s) => ({
          accentColor: accentColor ?? s.accentColor,
          logoUrl: logoUrl !== undefined ? logoUrl : s.logoUrl,
          systemName: systemName ?? s.systemName,
        }))
        if (accentColor) {
          document.documentElement.style.setProperty('--accent', accentColor)
        }
      },
    }),
    {
      name: 'vms-theme',
      onRehydrateStorage: () => (state) => {
        if (state?.accentColor) {
          document.documentElement.style.setProperty('--accent', state.accentColor)
        }
      },
    },
  ),
)
