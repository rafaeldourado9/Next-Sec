import { api } from './api'

export interface DashboardStats {
  cameras_total: number
  cameras_online: number
  detections_today: number
  recordings_total: number
}

export interface DetectionByHour {
  hour: string
  count: number
}

const STATS_FALLBACK: DashboardStats = {
  cameras_total: 0,
  cameras_online: 0,
  detections_today: 0,
  recordings_total: 0,
}

export const dashboardService = {
  async stats(): Promise<DashboardStats> {
    try {
      const res = await api.get<DashboardStats>('/dashboard/stats')
      return res.data
    } catch (err: unknown) {
      if (isNotFound(err)) return STATS_FALLBACK
      throw err
    }
  },

  async detectionsByHour(): Promise<DetectionByHour[]> {
    try {
      const res = await api.get<DetectionByHour[]>('/dashboard/detections-by-hour')
      return res.data
    } catch (err: unknown) {
      if (isNotFound(err)) return buildEmptyHours()
      throw err
    }
  },
}

function isNotFound(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'response' in err &&
    (err as { response?: { status?: number } }).response?.status === 404
  )
}

function buildEmptyHours(): DetectionByHour[] {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: `${i.toString().padStart(2, '0')}:00`,
    count: 0,
  }))
}
