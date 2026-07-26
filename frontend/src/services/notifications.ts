import { api } from './api'
import type { NotificationRule, NotificationLog } from '@/types'

interface CreateRuleData {
  name: string
  event_type_pattern: string
  destination_url: string
  webhook_secret?: string
}

interface UpdateRuleData {
  name?: string
  event_type_pattern?: string
  destination_url?: string
  is_active?: boolean
}

interface LogListResponse {
  items: NotificationLog[]
  total: number
  page: number
  page_size: number
  pages: number
}

interface ListLogsParams {
  rule_id?: string
  page?: number
  page_size?: number
}

export const notificationsService = {
  async listRules(): Promise<NotificationRule[]> {
    const res = await api.get<NotificationRule[]>('/notifications/rules')
    return res.data
  },

  async createRule(data: CreateRuleData): Promise<NotificationRule> {
    const res = await api.post<NotificationRule>('/notifications/rules', data)
    return res.data
  },

  async updateRule(id: string, data: UpdateRuleData): Promise<NotificationRule> {
    const res = await api.patch<NotificationRule>(`/notifications/rules/${id}`, data)
    return res.data
  },

  async deleteRule(id: string): Promise<void> {
    await api.delete(`/notifications/rules/${id}`)
  },

  async listLogs(params?: ListLogsParams): Promise<LogListResponse> {
    const res = await api.get<LogListResponse>('/notifications/logs', { params })
    return res.data
  },
}
