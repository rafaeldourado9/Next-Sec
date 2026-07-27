import { api } from './api'

export interface WhatsAppStatus {
  connected: boolean
  status: string
}

export interface WhatsAppQr {
  qr: string | null
  status: string
}

export const whatsappService = {
  async getStatus(): Promise<WhatsAppStatus> {
    const { data } = await api.get('/whatsapp/status')
    return data
  },

  async connect(): Promise<WhatsAppQr> {
    const { data } = await api.post('/whatsapp/connect')
    return data
  },

  async disconnect(): Promise<void> {
    await api.post('/whatsapp/disconnect')
  },
}
