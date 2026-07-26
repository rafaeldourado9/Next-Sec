import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User, AuthTokens } from '@/types'

/** Tempo de inatividade máximo antes do logout automático (15 minutos) */
const INACTIVITY_TIMEOUT_MS = 15 * 60 * 1000

/** Intervalo para refresh automático do token (5 minutos) */
const AUTO_REFRESH_INTERVAL_MS = 5 * 60 * 1000

interface AuthState {
  user: User | null
  tokens: AuthTokens | null
  lastActivity: number
  isAuthenticated: () => boolean
  login: (tokens: AuthTokens, user: User) => void
  logout: () => void
  setTokens: (tokens: AuthTokens) => void
  touchActivity: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      tokens: null,
      lastActivity: Date.now(),

      isAuthenticated: () => !!get().tokens?.access_token,

      login: (tokens, user) => set({ tokens, user, lastActivity: Date.now() }),

      logout: () => set({ tokens: null, user: null, lastActivity: 0 }),

      setTokens: (tokens) => set({ tokens }),

      touchActivity: () => set({ lastActivity: Date.now() }),
    }),
    {
      name: 'vms-auth',
      // Não persistir lastActivity (sempre recalcula no load)
      partialize: (state) => ({
        user: state.user,
        tokens: state.tokens,
      }),
    },
  ),
)

// ─── Timeout de inatividade ───────────────────────────────────────────────────

let inactivityTimer: ReturnType<typeof setTimeout> | null = null

function resetInactivityTimer() {
  if (inactivityTimer) clearTimeout(inactivityTimer)

  inactivityTimer = setTimeout(() => {
    const state = useAuthStore.getState()
    if (state.isAuthenticated()) {
      useAuthStore.getState().logout()
      window.location.href = '/login?reason=inactivity'
    }
  }, INACTIVITY_TIMEOUT_MS)
}

// Rastrear atividade do usuário
function setupActivityTracking() {
  const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click']
  const handler = () => {
    useAuthStore.getState().touchActivity()
    resetInactivityTimer()
  }
  events.forEach((evt) => window.addEventListener(evt, handler, { passive: true }))
  return () => events.forEach((evt) => window.removeEventListener(evt, handler))
}

// ─── Refresh token automático silencioso ──────────────────────────────────────

let autoRefreshTimer: ReturnType<typeof setInterval> | null = null

async function startAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)

  autoRefreshTimer = setInterval(async () => {
    const state = useAuthStore.getState()
    if (!state.isAuthenticated()) return

    const refreshToken = state.tokens?.refresh_token
    if (!refreshToken) return

    try {
      const res = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })

      if (!res.ok) {
        useAuthStore.getState().logout()
        window.location.href = '/login?reason=expired'
        return
      }

      const data = await res.json()
      const currentTokens = state.tokens!
      useAuthStore.getState().setTokens({ ...currentTokens, ...data })
    } catch {
      // Silencioso — o interceptor de 401 cuida disso
    }
  }, AUTO_REFRESH_INTERVAL_MS)
}

// ─── Inicialização ────────────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  setupActivityTracking()
  resetInactivityTimer()
  startAutoRefresh()
}
