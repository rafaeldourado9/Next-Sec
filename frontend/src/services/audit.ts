import { api } from './api'

export interface AuditLogItem {
  id: string
  tenant_id: string
  user_id: string | null
  user_email: string | null
  user_role: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  resource_name: string | null
  ip_address: string | null
  request_id: string | null
  result: string
  occurred_at: string
}

export interface AuditLogResponse {
  items: AuditLogItem[]
  total: number
  page: number
  page_size: number
}

export const auditService = {
  async list(params: {
    page?: number
    page_size?: number
    action?: string
    user_id?: string
    resource_type?: string
    from?: string
    to?: string
  } = {}): Promise<AuditLogResponse> {
    const { data } = await api.get('/audit/logs', { params })
    return data
  },
}
