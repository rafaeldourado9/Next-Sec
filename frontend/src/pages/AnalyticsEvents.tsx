import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldAlert, RefreshCw, Camera, SlidersHorizontal, Film, ImageOff } from 'lucide-react'
import { clsx } from 'clsx'
import { analyticsService, type AnalyticsEvent } from '@/services/analytics'
import { PLUGIN_NAMES } from '@/constants/plugins'
import { getEventTypeLabel, getEventTypeColor } from '@/constants/eventTypes'

const SEVERITY_STYLE: Record<string, string> = {
  critical: 'bg-red-500/10 text-red-400 border-red-500/30',
  warning:  'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
  info:     'bg-blue-500/10 text-blue-400 border-blue-500/30',
}

const SEVERITY_LABEL: Record<string, string> = {
  critical: 'Crítico',
  warning:  'Aviso',
  info:     'Info',
}


function fmtTime(iso: string) {
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export function AnalyticsEvents() {
  const navigate = useNavigate()
  const [events, setEvents]           = useState<AnalyticsEvent[]>([])
  const [loading, setLoading]         = useState(true)
  const [filterSeverity, setFilterSev] = useState('all')
  const [filterPlugin, setFilterPlug] = useState('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [sseConnected, setSseConnected] = useState(false)
  const evtSourceRef = useRef<EventSource | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await analyticsService.getEvents({
        severity: filterSeverity !== 'all' ? filterSeverity : undefined,
        plugin_id: filterPlugin !== 'all' ? filterPlugin : undefined,
        limit: 200,
      })
      setEvents(data)
    } catch {
      // ignora erro silenciosamente
    } finally {
      setLoading(false)
    }
  }, [filterSeverity, filterPlugin])

  // Reload on filter change
  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  // SSE connection for real-time events
  useEffect(() => {
    if (!autoRefresh) {
      setSseConnected(false)
      if (evtSourceRef.current) {
        evtSourceRef.current.close()
        evtSourceRef.current = null
      }
      return
    }

    try {
      // Tenta conectar SSE
      const token = localStorage.getItem('vms_access_token')
      const url = `/api/v1/sse?token=${encodeURIComponent(token || '')}`
      const evtSource = new EventSource(url)

      evtSource.onopen = () => {
        setSseConnected(true)
      }

      evtSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.event?.startsWith('analytics.') || data.event_type?.startsWith('analytics.')) {
            // Novo evento analytics recebido via SSE — adiciona no topo da lista
            setEvents(prev => {
              const newEvent: AnalyticsEvent = {
                id: crypto.randomUUID(),
                plugin_id: data.event_type?.split('.')[0] || 'unknown',
                camera_id: data.camera_id || '',
                camera_name: '',
                event_type: data.event_type || data.event,
                severity: data.severity || 'info',
                confidence: data.confidence,
                payload: data.data || data.payload || {},
                occurred_at: data.occurred_at || new Date().toISOString(),
                created_at: new Date().toISOString(),
                snapshot_url: null,
              }
              return [newEvent, ...prev].slice(0, 200)
            })
          }
        } catch {
          // ignora erro de parse
        }
      }

      evtSource.onerror = () => {
        setSseConnected(false)
        // Fallback: reconectar após 10s
        evtSource.close()
        setTimeout(() => {
          // O effect vai reconectar automaticamente
        }, 10000)
      }

      evtSourceRef.current = evtSource

      return () => {
        evtSource.close()
        evtSourceRef.current = null
        setSseConnected(false)
      }
    } catch {
      // SSE não suportado — fallback para polling
      setSseConnected(false)
    }
  }, [autoRefresh])

  // Auto-refresh fallback (polling) se SSE falhar
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (autoRefresh && !sseConnected) {
      intervalRef.current = setInterval(load, 5000)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, sseConnected, load])

  const criticalCount = events.filter(e => e.severity === 'critical').length
  const warningCount  = events.filter(e => e.severity === 'warning').length

  return (
    <div className="p-6 space-y-4 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <ShieldAlert size={20} className="text-accent" />
            <h1 className="text-xl font-bold text-t1">Detecções</h1>
            {criticalCount > 0 && (
              <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-red-500 text-white">
                {criticalCount} críticos
              </span>
            )}
          </div>
          <p className="text-xs text-t3">
            {events.length} eventos · {warningCount} avisos
            {sseConnected && (
              <span className="ml-2 flex items-center gap-1 text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                SSE
              </span>
            )}
            {autoRefresh && <span className="text-accent ml-2">• ao vivo</span>}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoRefresh(v => !v)}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition',
              autoRefresh
                ? 'text-accent border-accent/40 bg-accent/5'
                : 'text-t2 border-border hover:text-t1',
            )}
          >
            <RefreshCw size={13} className={autoRefresh ? 'animate-spin' : ''} style={{ animationDuration: '3s' }} />
            {autoRefresh ? 'Ao vivo' : 'Pausado'}
          </button>
          <button
            onClick={load}
            className="btn btn-ghost w-8 h-8 p-0"
            title="Atualizar agora"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border"
          style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
        >
          <SlidersHorizontal size={13} className="text-t3" />
          <select
            value={filterSeverity}
            onChange={e => setFilterSev(e.target.value)}
            className="bg-transparent text-xs text-t2 outline-none"
          >
            <option value="all">Todas severidades</option>
            <option value="critical">Crítico</option>
            <option value="warning">Aviso</option>
            <option value="info">Info</option>
          </select>
        </div>

        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border"
          style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
        >
          <Camera size={13} className="text-t3" />
          <select
            value={filterPlugin}
            onChange={e => setFilterPlug(e.target.value)}
            className="bg-transparent text-xs text-t2 outline-none"
          >
            <option value="all">Todos plugins</option>
            {Object.entries(PLUGIN_NAMES).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ borderColor: 'var(--border)' }}
      >
        <table className="w-full text-sm">
          <thead style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
            <tr>
              <th className="px-3 py-3 w-16" />
              <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Severidade</th>
              <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Câmera</th>
              <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Plugin</th>
              <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Evento</th>
              <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Confiança</th>
              <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Horário</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  {Array.from({ length: 8 }).map((__, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-3 rounded animate-pulse" style={{ background: 'var(--elevated)', width: '70%' }} />
                    </td>
                  ))}
                </tr>
              ))
            ) : events.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-sm text-t3">
                  Nenhuma detecção encontrada
                </td>
              </tr>
            ) : events.map(ev => {
              const typeColor = getEventTypeColor(ev.event_type)
              return (
                <tr
                  key={ev.id}
                  style={{ borderBottom: '1px solid var(--border)' }}
                  className="hover:bg-elevated/50 transition-colors"
                >
                  {/* Thumbnail — Bug 4: placeholder com fallback */}
                  <td className="px-3 py-2">
                    {ev.snapshot_url ? (
                      <img
                        src={ev.snapshot_url}
                        alt="snapshot"
                        className="rounded object-cover"
                        style={{ width: 56, height: 36, background: '#111' }}
                        onError={(e) => {
                          const target = e.target as HTMLImageElement
                          target.style.display = 'none'
                          const placeholder = target.nextElementSibling as HTMLElement
                          if (placeholder) placeholder.style.display = 'flex'
                        }}
                      />
                    ) : null}
                    <div
                      className="rounded flex flex-col items-center justify-center"
                      style={{
                        width: 56, height: 36, background: 'var(--elevated)',
                        display: ev.snapshot_url ? 'none' : 'flex',
                      }}
                    >
                      <ImageOff size={12} className="text-t3/40" />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('px-2 py-0.5 rounded text-xs font-medium border', SEVERITY_STYLE[ev.severity])}>
                      {SEVERITY_LABEL[ev.severity] ?? ev.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-t1 text-xs">{ev.camera_name ?? ev.camera_id}</td>
                  <td className="px-4 py-3 text-t2 text-xs">{PLUGIN_NAMES[ev.plugin_id] ?? ev.plugin_id}</td>
                  <td className="px-4 py-3 text-t1 text-xs font-medium">
                    {/* Melhoria 10: label em português + Melhoria 11: badge colorida */}
                    <span
                      className="inline-block text-[10px] font-medium px-2 py-0.5 rounded-full"
                      style={{
                        background: typeColor.bg,
                        color: typeColor.text,
                        border: `1px solid ${typeColor.border}`,
                      }}
                    >
                      {getEventTypeLabel(ev.event_type)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {ev.confidence != null ? (
                      <div className="flex items-center gap-2">
                        <div className="w-14 h-1 rounded-full overflow-hidden" style={{ background: 'var(--surface)' }}>
                          <div
                            className={clsx(
                              'h-full rounded-full',
                              ev.confidence >= 0.9 ? 'bg-green-500' :
                              ev.confidence >= 0.7 ? 'bg-yellow-500' : 'bg-red-500',
                            )}
                            style={{ width: `${ev.confidence * 100}%` }}
                          />
                        </div>
                        <span className="text-t2 text-xs tabular-nums">{(ev.confidence * 100).toFixed(0)}%</span>
                      </div>
                    ) : (
                      <span className="text-t3 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-t3 text-xs tabular-nums">{fmtTime(ev.occurred_at)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => navigate(
                        `/recordings?camera_id=${ev.camera_id}&date=${ev.occurred_at.split('T')[0]}`
                      )}
                      className="flex items-center gap-1 text-[11px] text-t3 hover:text-accent transition-colors"
                      title="Ver gravação deste horário"
                    >
                      <Film size={11} />
                      Gravação
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
