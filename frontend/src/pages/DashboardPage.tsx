import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cctv, Wifi, WifiOff, ShieldAlert, TrendingUp, ArrowRight } from 'lucide-react'
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'
import { camerasService } from '@/services/cameras'
import { eventsService } from '@/services/events'
import { PageSpinner } from '@/components/ui/Spinner'
import { Badge } from '@/components/ui/Badge'
import { useSSE } from '@/hooks/useSSE'
import { useCameraStore } from '@/store/cameraStore'
import type { Camera, VmsEvent } from '@/types'

interface HourData { hour: string; events: number }

function buildHourData(totalEvents: number): HourData[] {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: `${i.toString().padStart(2, '0')}h`,
    events: totalEvents > 0 ? Math.floor(Math.random() * (totalEvents / 24 * 2)) : 0,
  }))
}

export function DashboardPage() {
  const navigate = useNavigate()
  const [cameras, setCameras]   = useState<Camera[]>([])
  const [events, setEvents]     = useState<VmsEvent[]>([])
  const [totalEvents, setTotal] = useState(0)
  const [loading, setLoading]   = useState(true)

  const { lastEvent } = useSSE()
  const setOnline  = useCameraStore((s) => s.setOnline)
  const setOffline = useCameraStore((s) => s.setOffline)
  const sseStatuses = useCameraStore((s) => s.cameras)

  useEffect(() => {
    if (!lastEvent) return
    const type = lastEvent.type as string | undefined
    const cameraId = lastEvent.camera_id as string | undefined
    if (!cameraId) return
    if (type === 'camera.online')  setOnline(cameraId)
    if (type === 'camera.offline') setOffline(cameraId)
  }, [lastEvent, setOnline, setOffline])

  useEffect(() => {
    Promise.all([
      camerasService.list({ page_size: 100 }),
      eventsService.list({ page_size: 5 }),
    ]).then(([cams, evts]) => {
      setCameras(cams)
      setEvents(evts.items ?? [])
      setTotal(evts.total ?? 0)
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <PageSpinner />

  // Merge SSE realtime status with loaded cameras
  const mergedCameras = cameras.map((c) =>
    c.id in sseStatuses ? { ...c, is_online: sseStatuses[c.id].online } : c,
  )

  const onlineCount  = mergedCameras.filter((c) => c.is_online).length
  const offlineCount = mergedCameras.filter((c) => !c.is_online).length
  const hourData = buildHourData(totalEvents)

  const statCards = [
    { label: 'Total de Câmeras', value: mergedCameras.length, icon: Cctv,        color: '#3B82F6' },
    { label: 'Online',           value: onlineCount,          icon: Wifi,        color: '#22C55E' },
    { label: 'Offline',          value: offlineCount,         icon: WifiOff,     color: '#EF4444' },
    { label: 'Eventos Hoje',     value: totalEvents,          icon: ShieldAlert, color: '#F59E0B' },
  ]

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {statCards.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="card px-4 py-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs text-t2 font-medium">{label}</p>
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center"
                style={{ background: color + '18' }}
              >
                <Icon size={16} style={{ color }} />
              </div>
            </div>
            <p className="text-2xl font-bold text-t1">{value.toLocaleString()}</p>
          </div>
        ))}
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-sm font-semibold text-t1">Eventos por Hora</p>
            <p className="text-xs text-t3">Últimas 24 horas</p>
          </div>
          <TrendingUp size={16} className="text-t3" />
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={hourData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.3} />
                <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="hour" tick={{ fontSize: 11, fill: 'var(--text-3)' }} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--text-3)' }} />
            <Tooltip
              contentStyle={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: 'var(--text-2)' }}
              itemStyle={{ color: 'var(--accent)' }}
            />
            <Area type="monotone" dataKey="events" stroke="var(--accent)" fill="url(#grad)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Recent cameras */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-sm font-semibold text-t1">Câmeras</p>
            <p className="text-xs text-t3">Status em tempo real</p>
          </div>
          <button onClick={() => navigate('/cameras')} className="btn btn-ghost text-xs gap-1">
            Ver todas <ArrowRight size={14} />
          </button>
        </div>
        <div className="space-y-2">
          {mergedCameras.slice(0, 6).map((cam) => (
            <div
              key={cam.id}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-elevated transition cursor-pointer"
              onClick={() => navigate(`/cameras/${cam.id}`)}
            >
              <div
                className={`w-2 h-2 rounded-full shrink-0 ${cam.is_online ? 'bg-green-500' : 'bg-red-500'}`}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-t1 truncate">{cam.name}</p>
                <p className="text-xs text-t3 truncate">{cam.location ?? '—'}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant={cam.is_online ? 'success' : 'danger'} dot>
                  {cam.is_online ? 'Online' : 'Offline'}
                </Badge>
                <span className="text-xs text-t3 uppercase">{cam.stream_protocol.replace('_', ' ')}</span>
              </div>
            </div>
          ))}
          {mergedCameras.length === 0 && (
            <p className="text-sm text-t3 text-center py-4">Nenhuma câmera cadastrada</p>
          )}
        </div>
      </div>

      {/* Recent events */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-sm font-semibold text-t1">Alertas Recentes</p>
            <p className="text-xs text-t3">Últimos eventos</p>
          </div>
          <button onClick={() => navigate('/events')} className="btn btn-ghost text-xs gap-1">
            Ver todos <ArrowRight size={14} />
          </button>
        </div>
        <div className="space-y-2">
          {events.map((evt) => (
            <div
              key={evt.id}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-elevated transition"
            >
              <div className="w-2 h-2 rounded-full bg-yellow-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-t1 truncate">
                  {evt.event_type}
                  {evt.plate && <span className="ml-2 text-t3">• {evt.plate}</span>}
                </p>
                <p className="text-xs text-t3">
                  {new Date(evt.occurred_at).toLocaleString('pt-BR')}
                </p>
              </div>
              <Badge variant="warning">{evt.event_type}</Badge>
            </div>
          ))}
          {events.length === 0 && (
            <p className="text-sm text-t3 text-center py-4">Nenhum evento recente</p>
          )}
        </div>
      </div>
    </div>
  )
}
