import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity, Filter, RefreshCw, X, Film,
  ChevronLeft, ChevronRight, ZoomIn, ImageOff,
} from 'lucide-react'
import toast from 'react-hot-toast'
import axios from 'axios'
import { clsx } from 'clsx'
import { analyticsService, type AnalyticsEvent } from '@/services/analytics'
import { camerasService } from '@/services/cameras'
import { useSSE } from '@/hooks/useSSE'
import { PLUGIN_NAMES, SEV_STYLE } from '@/constants/plugins'
import { getEventTypeLabel, getEventTypeColor } from '@/constants/eventTypes'
import { AuthImage } from '@/components/ui/AuthImage'
import type { Camera } from '@/types'

const SEV_LABEL: Record<string, string> = {
  critical: 'Crítico',
  warning:  'Aviso',
  info:     'Info',
}

const SEVERITIES = ['critical', 'warning', 'info'] as const

const CLIENT_PAGE_SIZE = 25

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function BBoxOverlay({ payload }: { payload: Record<string, unknown> }) {
  const bbox = payload?.bbox
  if (!Array.isArray(bbox) || bbox.length !== 4) return null
  const [x1, y1, x2, y2] = bbox as number[]
  return (
    <div
      className="absolute border-2 border-red-500 rounded-sm pointer-events-none"
      style={{
        left: `${x1 * 100}%`,
        top: `${y1 * 100}%`,
        width: `${(x2 - x1) * 100}%`,
        height: `${(y2 - y1) * 100}%`,
      }}
    />
  )
}

function ConfBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-t3 text-xs">—</span>
  const pct = Math.round(value * 100)
  const color = pct >= 90 ? 'bg-green-500' : pct >= 70 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--surface)' }}>
        <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-t2 text-xs tabular-nums">{pct}%</span>
    </div>
  )
}

export function AnalyticsEventsPage() {
  const navigate = useNavigate()
  const [events, setEvents]   = useState<AnalyticsEvent[]>([])
  const [cameras, setCameras] = useState<Camera[]>([])
  const [loading, setLoading] = useState(true)
  const [lightboxEvent, setLightboxEvent] = useState<AnalyticsEvent | null>(null)
  const [enhancedSrc, setEnhancedSrc] = useState<string | null>(null)
  const [enhancing, setEnhancing] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [showFilters, setShowFilters] = useState(false)
  const [page, setPage] = useState(1)

  // Filters
  const [severity, setSeverity] = useState('')
  const [pluginId, setPluginId] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [confMin, setConfMin]   = useState('')

  const intervalRef  = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    camerasService.list().then(setCameras).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await analyticsService.getEvents({
        ...(severity  && { severity }),
        ...(pluginId  && { plugin_id: pluginId }),
        ...(cameraId  && { camera_id: cameraId }),
        ...(dateFrom  && { occurred_after:  `${dateFrom}T00:00:00` }),
        ...(dateTo    && { occurred_before: `${dateTo}T23:59:59` }),
        limit: 500,
      })
      setEvents(data)
    } catch {
      toast.error('Erro ao carregar eventos')
      setEvents([])
    } finally {
      setLoading(false)
    }
  }, [severity, pluginId, cameraId, dateFrom, dateTo])

  useEffect(() => { setPage(1) }, [severity, pluginId, cameraId, dateFrom, dateTo, confMin])
  useEffect(() => { load() }, [load])

  // SSE — real-time analytics events.
  // NOTA (Next Sec): a versão anterior montava a linha da tabela na mão a
  // partir da mensagem SSE, mas essa mensagem só carrega um resumo
  // ({event: "analytics.event", data: {event_type, camera_id, severity,
  // confidence, occurred_at}}) — sem snapshot, sem roi_name, sem bbox. O
  // código também lia os campos no nível errado (`d.camera_id` em vez de
  // `d.data.camera_id`), então vinham sempre vazios, e usava `d.event` como
  // se fosse o tipo real do evento (sempre "analytics.event", nunca
  // "analytics.intrusion.crossed") — plugin_id sempre saía "event". Mais
  // simples e correto: SSE só avisa "algo mudou", e a lista recarrega da API
  // de verdade (que já tem o formato certo).
  const { lastEvent, connected: sseConnected } = useSSE()
  const lastSeenSeqRef = useRef<unknown>(null)

  useEffect(() => {
    if (!autoRefresh || !lastEvent || lastEvent === lastSeenSeqRef.current) return
    lastSeenSeqRef.current = lastEvent
    const inner = (lastEvent as { data?: { event_type?: string } }).data
    if (!inner?.event_type?.startsWith('analytics.')) return
    load()
  }, [lastEvent, autoRefresh, load])

  // Polling fallback if SSE unavailable
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (autoRefresh && !sseConnected) intervalRef.current = setInterval(load, 10000)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, sseConnected, load])

  // Client-side confidence filter
  const filtered = confMin
    ? events.filter(e => e.confidence != null && e.confidence >= Number(confMin) / 100)
    : events

  const totalPages = Math.ceil(filtered.length / CLIENT_PAGE_SIZE)
  const pageItems  = filtered.slice((page - 1) * CLIENT_PAGE_SIZE, page * CLIENT_PAGE_SIZE)

  const critCount = events.filter(e => e.severity === 'critical').length
  const warnCount = events.filter(e => e.severity === 'warning').length
  const hasFilters = !!(severity || pluginId || cameraId || dateFrom || dateTo || confMin)

  const pgStart = Math.max(1, Math.min(page - 2, totalPages - 4))
  const pgEnd   = Math.min(totalPages, Math.max(page + 2, 5))
  const pgNums  = Array.from({ length: Math.max(0, pgEnd - pgStart + 1) }, (_, i) => pgStart + i)

  const openLightbox = (ev: AnalyticsEvent) => {
    setLightboxEvent(ev)
    setEnhancedSrc(null)
  }

  const closeLightbox = () => {
    if (enhancedSrc) URL.revokeObjectURL(enhancedSrc)
    setLightboxEvent(null)
    setEnhancedSrc(null)
  }

  const handleAnalyze = async () => {
    if (!lightboxEvent) return
    setEnhancing(true)
    try {
      const url = await analyticsService.enhanceEvent(lightboxEvent.id)
      setEnhancedSrc(url)
    } catch (err) {
      const isTimeout = axios.isAxiosError(err) && (err.code === 'ECONNABORTED' || err.response?.status === 504)
      toast.error(isTimeout ? 'Análise demorou demais e foi cancelada' : 'Erro ao melhorar o frame')
    } finally {
      setEnhancing(false)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Lightbox */}
      {lightboxEvent && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/92 backdrop-blur-sm cursor-zoom-out"
          onClick={closeLightbox}
        >
          <button
            className="absolute top-5 right-5 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition"
            onClick={e => { e.stopPropagation(); closeLightbox() }}
          >
            <X size={18} />
          </button>
          <div onClick={e => e.stopPropagation()} className="cursor-default flex flex-col items-center gap-3">
            <div className="relative max-w-5xl max-h-[80vh]">
              {enhancedSrc ? (
                <img
                  src={enhancedSrc}
                  alt="Snapshot melhorado"
                  className="max-w-5xl max-h-[80vh] rounded-xl object-contain shadow-2xl"
                />
              ) : (
                <AuthImage
                  src={lightboxEvent.snapshot_url!}
                  alt="Snapshot"
                  className={clsx(
                    'max-w-5xl max-h-[80vh] rounded-xl object-contain shadow-2xl transition block',
                    enhancing && 'opacity-30 blur-sm',
                  )}
                />
              )}
              {!enhancedSrc && !enhancing && <BBoxOverlay payload={lightboxEvent.payload} />}
              {enhancing && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-xl bg-black/30">
                  <div className="w-10 h-10 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                  <span className="text-xs text-white/80">Restaurando detalhe do frame (pode levar até 1 min)...</span>
                </div>
              )}
            </div>
            <button
              className="btn btn-primary gap-2"
              onClick={handleAnalyze}
              disabled={enhancing || !!enhancedSrc}
            >
              {enhancing ? 'Analisando...' : enhancedSrc ? 'Frame melhorado' : 'Analisar Evento'}
            </button>
          </div>
        </div>
      )}

      <div className="p-6 space-y-4 overflow-y-auto flex-1">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-3 mb-1 flex-wrap">
              <div className="flex items-center gap-2">
                <Activity size={20} className="text-accent" />
                <h1 className="text-xl font-bold text-t1">Eventos Analíticos</h1>
              </div>
              {critCount > 0 && (
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-red-500/10 text-red-400 border border-red-500/30">
                  {critCount} crítico{critCount > 1 ? 's' : ''}
                </span>
              )}
              {warnCount > 0 && (
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-yellow-500/10 text-yellow-400 border border-yellow-500/30">
                  {warnCount} aviso{warnCount > 1 ? 's' : ''}
                </span>
              )}
            </div>
            <p className="text-xs text-t3 flex items-center gap-2">
              <span>{filtered.length} evento{filtered.length !== 1 ? 's' : ''}</span>
              {sseConnected && (
                <span className="flex items-center gap-1 text-green-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  ao vivo
                </span>
              )}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              data-testid="autorefresh-btn"
              onClick={() => setAutoRefresh(v => !v)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition',
                autoRefresh ? 'text-accent border-accent/40 bg-accent/5' : 'text-t2 border-border hover:text-t1',
              )}
            >
              <RefreshCw
                size={13}
                className={autoRefresh ? 'animate-spin' : ''}
                style={{ animationDuration: '3s' }}
              />
              {autoRefresh ? 'Ao vivo' : 'Pausado'}
            </button>
            <button
              data-testid="toggle-filters-btn"
              onClick={() => setShowFilters(v => !v)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition',
                showFilters || hasFilters
                  ? 'text-accent border-accent/40 bg-accent/5'
                  : 'text-t2 border-border hover:text-t1',
              )}
            >
              <Filter size={13} />
              Filtros
              {hasFilters && <span className="w-1.5 h-1.5 rounded-full bg-accent" />}
            </button>
            <button data-testid="refresh-btn" onClick={load} className="btn btn-ghost w-8 h-8 p-0" title="Atualizar">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Severity chips */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setSeverity('')}
            className={clsx(
              'px-3 py-1 rounded-full text-xs font-medium border transition',
              !severity ? 'text-white border-transparent' : 'text-t2 border-border hover:text-t1',
            )}
            style={!severity ? { background: 'var(--accent)', borderColor: 'var(--accent)' } : {}}
          >
            Todos ({events.length})
          </button>
          {SEVERITIES.map(s => {
            const count  = events.filter(e => e.severity === s).length
            const style  = SEV_STYLE[s]
            const active = severity === s
            return (
              <button
                key={s}
                onClick={() => setSeverity(active ? '' : s)}
                className="px-3 py-1 rounded-full text-xs font-medium border transition"
                style={active
                  ? { background: style.bg, color: style.text, borderColor: `${style.dot}60` }
                  : { background: 'transparent', color: 'var(--text-2)', borderColor: 'var(--border)' }
                }
              >
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: style.dot }} />
                  {SEV_LABEL[s]} ({count})
                </span>
              </button>
            )
          })}
        </div>

        {/* Advanced filter panel */}
        {showFilters && (
          <div
            className="rounded-xl border p-4 space-y-3"
            style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
          >
            <div className="flex gap-2 flex-wrap">
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-lg border min-w-48"
                style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
              >
                <select
                  value={pluginId}
                  onChange={e => setPluginId(e.target.value)}
                  className="bg-transparent text-xs text-t2 outline-none w-full"
                >
                  <option value="">Todos os plugins</option>
                  {Object.entries(PLUGIN_NAMES).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </div>
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-lg border min-w-48"
                style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
              >
                <select
                  value={cameraId}
                  onChange={e => setCameraId(e.target.value)}
                  className="bg-transparent text-xs text-t2 outline-none w-full"
                >
                  <option value="">Todas as câmeras</option>
                  {cameras.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div
              className="flex gap-3 flex-wrap pt-3 border-t"
              style={{ borderColor: 'var(--border)' }}
            >
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-t3 uppercase tracking-wider">Data inicial</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={e => setDateFrom(e.target.value)}
                  className="px-3 py-1.5 rounded-lg border text-xs text-t1 bg-transparent outline-none"
                  style={{ borderColor: 'var(--border)' }}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-t3 uppercase tracking-wider">Data final</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={e => setDateTo(e.target.value)}
                  className="px-3 py-1.5 rounded-lg border text-xs text-t1 bg-transparent outline-none"
                  style={{ borderColor: 'var(--border)' }}
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-t3 uppercase tracking-wider">Confiança mínima</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={0} max={100} step={5}
                    value={confMin || '0'}
                    onChange={e => setConfMin(e.target.value === '0' ? '' : e.target.value)}
                    className="w-28 accent-[color:var(--accent)]"
                  />
                  <span className="text-xs text-t2 tabular-nums w-10">
                    {confMin ? `${confMin}%` : 'Tudo'}
                  </span>
                </div>
              </div>
              {hasFilters && (
                <button
                  onClick={() => { setSeverity(''); setPluginId(''); setCameraId(''); setDateFrom(''); setDateTo(''); setConfMin('') }}
                  className="self-end px-3 py-1.5 rounded-lg border text-xs text-t2 hover:text-danger transition"
                  style={{ borderColor: 'var(--border)' }}
                >
                  Limpar filtros
                </button>
              )}
            </div>
          </div>
        )}

        {/* Table */}
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
          <table className="w-full text-sm">
            <thead style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
              <tr>
                <th className="px-3 py-3 w-24" />
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Severidade</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Câmera</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Plugin</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Evento</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Confiança</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Horário</th>
                <th className="px-4 py-3 w-24" />
              </tr>
            </thead>
            <tbody data-testid="events-table-body">
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} data-testid="events-skeleton" style={{ borderBottom: '1px solid var(--border)' }}>
                    {[20, 40, 60, 50, 60, 40, 60, 20].map((w, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-3 rounded animate-pulse"
                          style={{ background: 'var(--elevated)', width: `${w}%` }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : pageItems.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-16 text-center">
                    <div data-testid="empty-state" className="flex flex-col items-center gap-3 text-t3">
                      <Activity size={36} className="opacity-25" />
                      <span className="text-sm">Nenhum evento encontrado</span>
                      {hasFilters && (
                        <button
                          onClick={() => { setSeverity(''); setPluginId(''); setCameraId(''); setDateFrom(''); setDateTo(''); setConfMin('') }}
                          className="text-xs text-accent hover:underline"
                        >
                          Limpar filtros
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ) : pageItems.map(ev => {
                const sevStyle  = SEV_STYLE[ev.severity] ?? SEV_STYLE.info
                const typeColor = getEventTypeColor(ev.event_type)
                return (
                  <tr
                    key={ev.id}
                    data-testid="event-row"
                    style={{ borderBottom: '1px solid var(--border)' }}
                    className="hover:bg-elevated/40 transition-colors"
                  >
                    {/* Snapshot */}
                    <td className="px-3 py-2">
                      <div
                        className="relative group rounded overflow-hidden"
                        style={{
                          width: 76, height: 48,
                          background: 'var(--elevated)',
                          cursor: ev.snapshot_url ? 'zoom-in' : 'default',
                        }}
                        onClick={() => ev.snapshot_url && openLightbox(ev)}
                      >
                        {ev.snapshot_url ? (
                          <>
                            <AuthImage
                              src={ev.snapshot_url}
                              alt="snapshot"
                              className="w-full h-full object-cover"
                              style={{ background: 'var(--elevated)' }}
                            />
                            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition flex items-center justify-center opacity-0 group-hover:opacity-100">
                              <ZoomIn size={14} className="text-white drop-shadow" />
                            </div>
                          </>
                        ) : (
                          <div className="w-full h-full flex items-center justify-center">
                            <ImageOff size={14} className="text-t3/40" />
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Severity badge */}
                    <td className="px-4 py-3">
                      <span
                        className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium border w-fit whitespace-nowrap"
                        style={{
                          background:  sevStyle.bg,
                          color:       sevStyle.text,
                          borderColor: `${sevStyle.dot}50`,
                        }}
                      >
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: sevStyle.dot }} />
                        {SEV_LABEL[ev.severity] ?? ev.severity}
                      </span>
                    </td>

                    {/* Camera */}
                    <td className="px-4 py-3 text-xs text-t1 max-w-36 truncate">
                      {ev.camera_name || ev.camera_id || '—'}
                    </td>

                    {/* Plugin */}
                    <td className="px-4 py-3 text-xs text-t2 whitespace-nowrap">
                      {PLUGIN_NAMES[ev.plugin_id] ?? ev.plugin_id}
                    </td>

                    {/* Event type */}
                    <td className="px-4 py-3">
                      <span
                        className="inline-block text-[10px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
                        style={{
                          background: typeColor.bg,
                          color:      typeColor.text,
                          border:     `1px solid ${typeColor.border}`,
                        }}
                      >
                        {getEventTypeLabel(ev.event_type)}
                      </span>
                    </td>

                    {/* Confidence */}
                    <td className="px-4 py-3">
                      <ConfBar value={ev.confidence} />
                    </td>

                    {/* Time */}
                    <td className="px-4 py-3 text-t3 text-xs tabular-nums whitespace-nowrap">
                      {fmtTime(ev.occurred_at)}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      {ev.camera_id && (
                        <button
                          onClick={() =>
                            navigate(`/recordings?camera_id=${ev.camera_id}&date=${ev.occurred_at.split('T')[0]}`)
                          }
                          className="flex items-center gap-1 text-[11px] text-t3 hover:text-accent transition-colors whitespace-nowrap"
                          title="Ver gravação"
                        >
                          <Film size={11} />
                          Gravação
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between text-xs text-t3">
            <span>
              Página {page} de {totalPages} · {filtered.length} evento{filtered.length !== 1 ? 's' : ''}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="w-8 h-8 rounded-lg flex items-center justify-center border text-t2 hover:text-t1 disabled:opacity-40 transition"
                style={{ borderColor: 'var(--border)' }}
              >
                <ChevronLeft size={14} />
              </button>
              {pgNums.map(p => (
                <button
                  key={p}
                  onClick={() => setPage(p)}
                  className={clsx(
                    'w-8 h-8 rounded-lg text-xs font-medium border transition',
                    p === page ? 'text-white' : 'text-t2 hover:text-t1',
                  )}
                  style={{
                    borderColor: p === page ? 'var(--accent)' : 'var(--border)',
                    background:  p === page ? 'var(--accent)' : 'transparent',
                  }}
                >
                  {p}
                </button>
              ))}
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="w-8 h-8 rounded-lg flex items-center justify-center border text-t2 hover:text-t1 disabled:opacity-40 transition"
                style={{ borderColor: 'var(--border)' }}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
