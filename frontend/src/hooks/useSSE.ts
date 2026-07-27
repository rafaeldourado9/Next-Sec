import { useEffect, useState } from 'react'
import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

interface SSEState {
  lastEvent: Record<string, unknown> | null
  connected: boolean
}

type Listener = (state: { lastEvent: Record<string, unknown> | null; connected: boolean }) => void

// Conexão SSE única, compartilhada por toda a aba — várias páginas/componentes
// chamam useSSE() ao mesmo tempo (Header + página atual, por exemplo). Cada
// chamada costumava abrir seu próprio EventSource; ao dar erro, cada uma
// tentava refresh de token de forma independente, multiplicando requests em
// POST /auth/refresh e estourando o rate-limit de nginx (zone "auth"), o que
// derrubava até o login normal. Agora existe só uma conexão + um único ciclo
// de reconexão/refresh por aba, não importa quantos componentes assinem.
let es: EventSource | null = null
let currentToken: string | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let backoff = 1000
let refreshing = false
const listeners = new Set<Listener>()

function notify(patch: { lastEvent?: Record<string, unknown> | null; connected?: boolean }) {
  for (const l of listeners) {
    l(patch as { lastEvent: Record<string, unknown> | null; connected: boolean })
  }
}

async function tryRefreshToken(): Promise<string | null> {
  const state = useAuthStore.getState()
  const refreshToken = state.tokens?.refresh_token
  if (!refreshToken) return null
  try {
    const res = await axios.post<{ access_token: string; refresh_token: string; expires_in: number }>(
      '/api/v1/auth/refresh',
      { refresh_token: refreshToken },
    )
    state.setTokens({ ...state.tokens!, ...res.data })
    return res.data.access_token
  } catch {
    state.logout()
    window.location.href = '/login'
    return null
  }
}

function teardown() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  es?.close()
  es = null
  currentToken = null
}

function connect(token: string) {
  teardown()
  currentToken = token
  const conn = new EventSource(`/api/v1/sse?token=${encodeURIComponent(token)}`)
  es = conn

  conn.onopen = () => {
    backoff = 1000
    notify({ connected: true })
  }

  conn.onmessage = (e: MessageEvent<string>) => {
    try {
      const data = JSON.parse(e.data) as Record<string, unknown>
      notify({ lastEvent: data })
    } catch {
      // heartbeat comment, ignorar
    }
  }

  conn.onerror = () => {
    notify({ connected: false })
    conn.close()
    if (es !== conn) return // já foi substituída por outra conexão
    es = null

    if (!refreshing) {
      refreshing = true
      tryRefreshToken().then((fresh) => {
        refreshing = false
        const delay = backoff
        backoff = Math.min(delay * 2, 30000)
        reconnectTimer = setTimeout(() => {
          const latest = fresh ?? useAuthStore.getState().tokens?.access_token
          if (latest) connect(latest)
        }, delay)
      })
    }
  }
}

export function useSSE(): SSEState {
  const token = useAuthStore((s) => s.tokens?.access_token)
  const [state, setState] = useState<SSEState>({ lastEvent: null, connected: es?.readyState === EventSource.OPEN })

  useEffect(() => {
    if (!token) return

    const listener: Listener = (patch) => setState((prev) => ({ ...prev, ...patch }))
    listeners.add(listener)

    if (!es || currentToken !== token) {
      connect(token)
    }

    return () => {
      listeners.delete(listener)
      if (listeners.size === 0) {
        teardown()
      }
    }
  }, [token])

  return state
}
