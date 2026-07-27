import { api } from './api'
import type { VmsEvent } from '@/types'

interface ListEventsParams {
  camera_id?: string
  event_type?: string
  source?: 'lpr' | 'analytics'
  plate?: string
  occurred_after?: string
  occurred_before?: string
  confidence_min?: number
  page?: number
  page_size?: number
}

interface EventListResponse {
  items: VmsEvent[]
  total: number
  page: number
  page_size: number
  pages: number
}

type ExportParams = Omit<ListEventsParams, 'page' | 'page_size'>

export const eventsService = {
  async list(params?: ListEventsParams): Promise<EventListResponse> {
    const res = await api.get<EventListResponse>('/events', { params })
    return res.data
  },

  async get(id: string): Promise<VmsEvent> {
    const res = await api.get<VmsEvent>(`/events/${id}`)
    return res.data
  },

  async exportCsv(params?: ExportParams): Promise<Blob> {
    const res = await api.get('/events/export/csv', { params, responseType: 'blob' })
    return res.data
  },

  async exportPdf(params?: ExportParams): Promise<Blob> {
    const res = await api.get('/events/export/pdf', { params, responseType: 'blob' })
    return res.data
  },
}
