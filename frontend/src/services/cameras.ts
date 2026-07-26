import { api } from './api'
import type { Camera, StreamUrls, RtmpConfig, StreamQuality } from '@/types'

interface ListCamerasParams {
  page?: number
  page_size?: number
  search?: string
}

interface CreateCameraData {
  name: string
  location?: string
  address?: string
  latitude?: number
  longitude?: number
  ia_enabled?: boolean
  ptz_supported?: boolean
  manufacturer?: string
  retention_days?: number
  stream_quality?: StreamQuality
  stream_protocol: string
  rtsp_url?: string
  onvif_url?: string
  onvif_username?: string
  onvif_password?: string
}

interface UpdateCameraData {
  name?: string
  location?: string
  address?: string
  latitude?: number | null
  longitude?: number | null
  ia_enabled?: boolean
  rtsp_url?: string
  onvif_url?: string
  onvif_username?: string
  onvif_password?: string
  manufacturer?: string
  retention_days?: number
  is_active?: boolean
}

export const camerasService = {
  async list(params?: ListCamerasParams): Promise<Camera[]> {
    const res = await api.get<Camera[]>('/cameras', { params })
    return res.data
  },

  async get(id: string): Promise<Camera> {
    const res = await api.get<Camera>(`/cameras/${id}`)
    return res.data
  },

  async create(data: CreateCameraData): Promise<Camera> {
    const res = await api.post<Camera>('/cameras', data)
    return res.data
  },

  async update(id: string, data: UpdateCameraData): Promise<Camera> {
    const res = await api.patch<Camera>(`/cameras/${id}`, data)
    return res.data
  },

  async del(id: string): Promise<void> {
    await api.delete(`/cameras/${id}`)
  },

  async streamUrls(id: string): Promise<StreamUrls> {
    const res = await api.get<StreamUrls>(`/cameras/${id}/stream-urls`)
    return res.data
  },

  async snapshot(id: string): Promise<string | null> {
    const res = await api.get<{ snapshot_url: string | null }>(`/cameras/${id}/snapshot`)
    return res.data.snapshot_url
  },

  async rtmpConfig(id: string): Promise<RtmpConfig> {
    const res = await api.get<RtmpConfig>(`/cameras/${id}/rtmp-config`)
    return res.data
  },

  async onvifProbe(data: { onvif_url: string; username: string; password: string }): Promise<unknown> {
    const res = await api.post('/cameras/onvif-probe', data)
    return res.data
  },

  async discover(data: { subnet?: string }): Promise<DiscoverOnvifResponse> {
    const res = await api.post<DiscoverOnvifResponse>('/cameras/discover', data)
    return res.data
  },
}

export interface DiscoveredCamera {
  onvif_url: string
  manufacturer: string | null
  model: string | null
  ip: string
}

export interface DiscoverOnvifResponse {
  cameras: DiscoveredCamera[]
  duration_ms: number
}
