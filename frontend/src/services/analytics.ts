import { api } from './api'

export interface AnalyticsCatalogItem {
  id: string
  name: string
  description: string
  version: string
  category: string
  model_size: string
  fps_cost: number
  is_available: boolean
  classes: string[]
}

export interface AnalyticsEvent {
  id: string
  plugin_id: string
  camera_id: string
  camera_name: string | null
  event_type: string
  severity: 'critical' | 'warning' | 'info'
  confidence: number | null
  payload: Record<string, unknown>
  occurred_at: string
  created_at: string
  snapshot_url: string | null
}

export interface AnalyticsStats {
  total: number
  by_severity: Record<string, number>
  by_plugin: Record<string, number>
  top_cameras: Array<{ camera_id: string; camera_name?: string; count: number }>
  period_hours: number
}

export interface ROI {
  id: string
  camera_id: string
  plugin_id: string
  name: string
  polygon: number[][]
  config: Record<string, unknown>
  is_active: boolean
  created_at: string
}

export interface ROICreatePayload {
  camera_id: string
  plugin_id: string
  name: string
  polygon: number[][]
  config?: Record<string, unknown>
}

export interface ROISchedule {
  id: string
  roi_id: string
  day_of_week: number | null
  start_time: string
  end_time: string
  is_active: boolean
}

export interface ROIScheduleCreatePayload {
  day_of_week?: number | null
  start_time: string
  end_time: string
}

export const analyticsService = {
  getCatalog: async (): Promise<AnalyticsCatalogItem[]> => {
    const { data } = await api.get<AnalyticsCatalogItem[]>('/analytics/catalog')
    return data
  },

  getEvents: async (params?: {
    camera_id?: string
    plugin_id?: string
    severity?: string
    occurred_after?: string
    occurred_before?: string
    limit?: number
  }): Promise<AnalyticsEvent[]> => {
    const { data } = await api.get<AnalyticsEvent[]>('/analytics/events', { params })
    return data
  },

  getStats: async (hours = 24): Promise<AnalyticsStats> => {
    const { data } = await api.get<AnalyticsStats>('/analytics/stats', { params: { hours } })
    return data
  },

  // GFPGAN (restauração de rosto) é CPU-bound e pode levar dezenas de
  // segundos numa máquina sem GPU — timeout generoso (o backend já corta em
  // 90s) só pra garantir um limite duro caso a resposta nunca volte.
  enhanceEvent: async (eventId: string): Promise<string> => {
    const { data } = await api.post(`/analytics/events/${eventId}/enhance`, null, {
      responseType: 'blob',
      timeout: 95_000,
    })
    return URL.createObjectURL(data as Blob)
  },

  listROIs: async (camera_id?: string, plugin_id?: string): Promise<ROI[]> => {
    const { data } = await api.get<ROI[]>('/analytics/rois', {
      params: { camera_id, plugin_id },
    })
    return data
  },

  createROI: async (payload: ROICreatePayload): Promise<ROI> => {
    const { data } = await api.post<ROI>('/analytics/rois', payload)
    return data
  },

  updateROI: async (id: string, payload: ROICreatePayload): Promise<ROI> => {
    const { data } = await api.put<ROI>(`/analytics/rois/${id}`, payload)
    return data
  },

  deleteROI: async (id: string): Promise<void> => {
    await api.delete(`/analytics/rois/${id}`)
  },

  listROISchedules: async (roiId: string): Promise<ROISchedule[]> => {
    const { data } = await api.get<ROISchedule[]>(`/analytics/rois/${roiId}/schedules`)
    return data
  },

  createROISchedule: async (
    roiId: string,
    payload: ROIScheduleCreatePayload,
  ): Promise<ROISchedule> => {
    const { data } = await api.post<ROISchedule>(`/analytics/rois/${roiId}/schedules`, payload)
    return data
  },

  deleteROISchedule: async (roiId: string, scheduleId: string): Promise<void> => {
    await api.delete(`/analytics/rois/${roiId}/schedules/${scheduleId}`)
  },
}
