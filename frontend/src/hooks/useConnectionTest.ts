import { useState } from 'react'
import { camerasService as camerasSvc } from '@/services/cameras'

interface OnvifProbeResponse {
  reachable: boolean
  manufacturer?: string | null
  model?: string | null
  rtsp_url?: string | null
  snapshot_url?: string | null
  error?: string | null
}

export type ConnectionTestStatus = 'idle' | 'loading' | 'ok' | 'error'

export interface ConnectionTestResult {
  status: ConnectionTestStatus
  manufacturer?: string
  model?: string
  rtsp_url?: string
  snapshot_url?: string
  error?: string
}

export function useConnectionTest() {
  const [result, setResult] = useState<ConnectionTestResult>({ status: 'idle' })

  async function testOnvif(onvif_url: string, username: string, password: string) {
    setResult({ status: 'loading' })
    try {
      const data = await camerasSvc.onvifProbe({ onvif_url, username, password }) as OnvifProbeResponse
      if (data.reachable) {
        setResult({
          status: 'ok',
          manufacturer: data.manufacturer ?? undefined,
          model: data.model ?? undefined,
          rtsp_url: data.rtsp_url ?? undefined,
          snapshot_url: data.snapshot_url ?? undefined,
        })
      } else {
        setResult({ status: 'error', error: data.error ?? 'Câmera inacessível' })
      }
    } catch {
      setResult({ status: 'error', error: 'Erro ao conectar com a câmera' })
    }
  }

  function reset() {
    setResult({ status: 'idle' })
  }

  return { result, testOnvif, reset }
}
