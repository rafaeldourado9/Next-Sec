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
  is_active: boolean
  created_at: string
}

export interface CameraConfigItem {
  camera_id: string
  name: string
  rtsp_url: string
  enabled: boolean
  rtmp_push_url: string
}

// Criação/edição/remoção de agent nativo (Nível 2) saiu do frontend — ver
// POST /admin/onboard-client (Sprint 7). `list()` continua aqui porque o
// AddCameraWizard usa pra vincular a câmera a um agent já existente.
export const agentsService = {
  async list(): Promise<Agent[]> {
    const { data } = await api.get('/agents')
    return data
  },
}
