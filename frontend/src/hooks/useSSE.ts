import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

interface SSEState {
  lastEvent: Record<string, unknown> | null
  connected: boolean
}

async function _tryRefreshToken(): Promise<string | null> {
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

export function useSSE(): SSEState {
  const token = useAuthStore((s) => s.tokens?.access_token)
  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<Record<string, unknown> | null>(null)
  const esRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const backoffRef = useRef(1000)
  const refreshingRef = useRef(false)

  useEffect(() => {
    if (!token) return

    const connect = (tok: string) => {
      esRef.current?.close()
      const es = new EventSource(`/api/v1/sse?token=${encodeURIComponent(tok)}`)
      esRef.current = es

      es.onopen = () => {
        setConnected(true)
        backoffRef.current = 1000
      }

      es.onmessage = (e: MessageEvent<string>) => {
        try {
          const data = JSON.parse(e.data) as Record<string, unknown>
          setLastEvent(data)
        } catch {
          // heartbeat comment, ignorar
        }
      }

      es.onerror = () => {
        setConnected(false)
        es.close()

        // Tenta refresh antes de reconectar
        if (!refreshingRef.current) {
          refreshingRef.current = true
          _tryRefreshToken().then(() => {
            refreshingRef.current = false
            const delay = backoffRef.current
            backoffRef.current = Math.min(delay * 2, 30000)
            timerRef.current = setTimeout(() => {
              const latest = useAuthStore.getState().tokens?.access_token
              if (latest) connect(latest)
            }, delay)
          })
        }
      }
    }

    connect(token)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      esRef.current?.close()
      setConnected(false)
    }
  }, [token])

  return { lastEvent, connected }
}
