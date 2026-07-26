import { api } from './api'

export interface HealthStatus {
  status: 'healthy' | 'degraded'
  services: Record<string, string>
  cameras_online: number
  cameras_total: number
  version: string
}

export interface Metrics {
  tenants: number
  users: number
  cameras_total: number
  cameras_online: number
  events_total: number
  active_streams: number
  version: string
}

export const healthService = {
  async check(): Promise<HealthStatus> {
    const { data } = await api.get('/health')
    return data
  },

  async metrics(): Promise<Metrics> {
    const { data } = await api.get('/metrics')
    return data
  },
}
