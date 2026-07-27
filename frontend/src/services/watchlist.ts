import { api } from './api'

export interface FaceProfile {
  id: string
  tenant_id: string
  name: string
  reference_image_path: string | null
  is_active: boolean
  created_at: string
}

export interface FaceSearchMatch {
  event_id: string
  camera_id: string
  similarity: number
  occurred_at: string
  snapshot_url: string
}

export const watchlistService = {
  async list(): Promise<FaceProfile[]> {
    const res = await api.get<FaceProfile[]>('/watchlist/faces')
    return res.data
  },

  async search(id: string): Promise<FaceSearchMatch[]> {
    const res = await api.post<FaceSearchMatch[]>(`/watchlist/faces/${id}/search`)
    return res.data
  },

  async create(name: string, image: File): Promise<FaceProfile> {
    const form = new FormData()
    form.append('name', name)
    form.append('image', image)
    const res = await api.post<FaceProfile>('/watchlist/faces', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  },

  async del(id: string): Promise<void> {
    await api.delete(`/watchlist/faces/${id}`)
  },
}
