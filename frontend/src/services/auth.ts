import { api } from './api'
import type { AuthTokens, User } from '@/types'

export const authService = {
  async login(email: string, password: string): Promise<AuthTokens> {
    const res = await api.post<AuthTokens>('/auth/token', { email, password })
    return res.data
  },

  async refresh(refreshToken: string): Promise<AuthTokens> {
    const res = await api.post<AuthTokens>('/auth/refresh', { refresh_token: refreshToken })
    return res.data
  },

  async me(accessToken?: string): Promise<User> {
    const config = accessToken
      ? { headers: { Authorization: `Bearer ${accessToken}` } }
      : {}
    const res = await api.get<User>('/users/me', config)
    return res.data
  },
}
