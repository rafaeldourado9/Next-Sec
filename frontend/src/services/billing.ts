import { api } from './api'

export interface BillingQuota {
  allowed: boolean
  current: number | null
  limit: number | null
  pct: number | null
}

export interface LicenseSummary {
  total_active: number
  by_type: Record<string, number>
  licenses: {
    id: string
    camera_id: string | null
    type: string
    status: string
    expires_at: string | null
    has_analytics: boolean
    storage_gb: number | null
  }[]
}

export const billingService = {
  async getSummary(): Promise<LicenseSummary> {
    const { data } = await api.get('/licenses')
    return data
  },

  async validateCamera(cameraId: string): Promise<{ is_valid: boolean; reason: string }> {
    const { data } = await api.get(`/licenses/cameras/${cameraId}/validate`)
    return data
  },

  async analyticsAllowed(cameraId: string): Promise<boolean> {
    const { data } = await api.get(`/licenses/cameras/${cameraId}/analytics-allowed`)
    return data
  },

  async getRetentionPolicies(): Promise<{ tenant_id: string; policies: { data_type: string; retention_days: number }[] }> {
    const { data } = await api.get('/lgpd/retention-policies')
    return data
  },
}
