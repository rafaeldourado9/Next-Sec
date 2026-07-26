import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/store/authStore'

let _refreshing: Promise<string | null> | null = null

const _apiBase = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

export const api: AxiosInstance = axios.create({
  baseURL: _apiBase,
  headers: { 'Content-Type': 'application/json' },
  // Desativar logs de debug do axios
  transformResponse: axios.defaults.transformResponse,
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().tokens?.access_token
  if (token && config.headers) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (err.response?.status === 401 && !original._retry) {
      original._retry = true

      const refreshToken = useAuthStore.getState().tokens?.refresh_token
      if (!refreshToken) {
        useAuthStore.getState().logout()
        window.location.href = '/login'
        return Promise.reject(err)
      }

      // Evita múltiplas requisições de refresh simultâneas
      if (!_refreshing) {
        _refreshing = (async (): Promise<string | null> => {
          try {
            const res = await axios.post<{ access_token: string; refresh_token: string }>(
              '/api/v1/auth/refresh',
              { refresh_token: refreshToken },
            )
            const newTokens = res.data
            const currentTokens = useAuthStore.getState().tokens!
            useAuthStore.getState().setTokens({ ...currentTokens, ...newTokens })
            return newTokens.access_token
          } catch {
            useAuthStore.getState().logout()
            window.location.href = '/login'
            return null
          } finally {
            _refreshing = null
          }
        })()
      }

      const newAccess = await _refreshing
      if (!newAccess) return Promise.reject(err)

      if (original.headers) {
        original.headers['Authorization'] = `Bearer ${newAccess}`
      }
      return api(original)
    }

    return Promise.reject(err)
  },
)
