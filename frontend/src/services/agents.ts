import { api } from './api'

export interface Agent {
  id: string
  tenant_id: string
  name: string
  hostname: string | null
  ip_address: string | null
  agent_version: string | null
  status: string        // pending | online | offline
  last_heartbeat_at: string | null
  streams_running: number
  streams_failed: number
  cpu_usage: number | null
  ram_usage: number | null
  created_at: string
}

export interface CameraConfigItem {
  camera_id: string
  name: string
  rtsp_url: string
  enabled: boolean
  rtmp_push_url: string
}

export const agentsService = {
  async list(): Promise<Agent[]> {
    const { data } = await api.get('/agents')
    return data
  },

  async create(name: string): Promise<Agent> {
    const { data } = await api.post('/agents', { name })
    return data
  },

  async delete(id: string): Promise<void> {
    await api.delete(`/agents/${id}`)
  },

  async update(id: string, updates: { name?: string; is_active?: boolean }): Promise<Agent> {
    const { data } = await api.put(`/agents/${id}`, updates)
    return data
  },
}
