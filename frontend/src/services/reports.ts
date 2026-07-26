import { api } from './api'

export interface ReportItem {
  id: string
  report_type: string
  status: string
  file_path: string | null
  generated_at: string | null
  created_at: string
}

export interface ReportListResponse {
  items: ReportItem[]
  total: number
  page: number
  page_size: number
}

export const reportsService = {
  async list(page = 1, pageSize = 20): Promise<ReportListResponse> {
    const { data } = await api.get('/reports', { params: { page, page_size: pageSize } })
    return data
  },

  async get(id: string): Promise<ReportItem> {
    const { data } = await api.get(`/reports/${id}`)
    return data
  },

  async create(reportType: string, parameters: Record<string, unknown> = {}): Promise<ReportItem> {
    const { data } = await api.post('/reports', { report_type: reportType, parameters })
    return data
  },

  async generateNow(id: string): Promise<ReportItem> {
    const { data } = await api.post(`/reports/${id}/generate-now`)
    return data
  },

  async download(id: string) {
    window.open(`${import.meta.env.VITE_API_URL || ''}/api/v1/reports/${id}/download`, '_blank')
  },
}
