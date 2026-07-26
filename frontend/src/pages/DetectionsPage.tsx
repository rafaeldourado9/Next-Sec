import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ScanLine, Search, Filter, RefreshCw, X, Film,
  ChevronLeft, ChevronRight, ZoomIn, ImageOff,
} from 'lucide-react'
import { clsx } from 'clsx'
import { eventsService } from '@/services/events'
import { camerasService } from '@/services/cameras'
import { getEventTypeLabel, getEventTypeColor } from '@/constants/eventTypes'
import { AuthImage } from '@/components/ui/AuthImage'
import type { VmsEvent, Camera } from '@/types'

const PAGE_SIZE = 25

function fmtTime(iso: string) {
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
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

export function DetectionsPage() {
  const navigate = useNavigate()
  const [events, setEvents]     = useState<VmsEvent[]>([])
  const [cameras, setCameras]   = useState<Camera[]>([])
  const [loading, setLoading]   = useState(true)
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)

  // Filters
  const [plate, setPlate]         = useState('')
  const [cameraId, setCameraId]   = useState('')
  const [dateFrom, setDateFrom]   = useState('')
  const [dateTo, setDateTo]       = useState('')
  const [confMin, setConfMin]     = useState('')
  const [showFilters, setShowFilters] = useState(false)

  // Pagination
  const [page, setPage]   = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)

  useEffect(() => {
    camerasService.list().then(setCameras).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await eventsService.list({
        source: 'lpr',
        page,
        page_size: PAGE_SIZE,
        ...(plate.trim() && { plate: plate.trim() }),
        ...(cameraId       && { camera_id: cameraId }),
        ...(dateFrom       && { occurred_after:  `${dateFrom}T00:00:00` }),
        ...(dateTo         && { occurred_before: `${dateTo}T23:59:59` }),
      })
      setEvents(res.items)
      setTotal(res.total)
      setPages(res.pages)
    } catch {
      setEvents([])
    } finally {
      setLoading(false)
    }
  }, [plate, cameraId, dateFrom, dateTo, page])

  useEffect(() => { setPage(1) }, [plate, cameraId, dateFrom, dateTo, confMin])
  useEffect(() => { load() }, [load])

  const displayed = confMin
    ? events.filter(e => e.confidence != null && e.confidence >= Number(confMin) / 100)
    : events

  const cameraName = (id: string | null) =>
    id ? (cameras.find(c => c.id === id)?.name ?? id) : '—'

  const hasFilters = !!(plate || cameraId || dateFrom || dateTo || confMin)

  // Pagination page numbers (up to 5 centered on current page)
  const pgStart = Math.max(1, Math.min(page - 2, pages - 4))
  const pgEnd   = Math.min(pages, Math.max(page + 2, 5))
  const pgNums  = Array.from({ length: pgEnd - pgStart + 1 }, (_, i) => pgStart + i)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Lightbox */}
      {lightboxSrc && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/92 backdrop-blur-sm cursor-zoom-out"
          onClick={() => setLightboxSrc(null)}
        >
          <button
            className="absolute top-5 right-5 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition"
            onClick={e => { e.stopPropagation(); setLightboxSrc(null) }}
          >
            <X size={18} />
          </button>
          <div onClick={e => e.stopPropagation()} className="cursor-default">
            <AuthImage
              src={lightboxSrc}
              alt="Snapshot"
              className="max-w-5xl max-h-[88vh] rounded-xl object-contain shadow-2xl"
            />
          </div>
        </div>
      )}

      <div className="p-6 space-y-4 overflow-y-auto flex-1">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <ScanLine size={20} className="text-accent" />
              <h1 className="text-xl font-bold text-t1">Detecções ALPR</h1>
              {!loading && total > 0 && (
                <span
                  className="px-2 py-0.5 rounded-full text-xs font-medium border text-t2"
                  style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
                >
                  {total.toLocaleString('pt-BR')}
                </span>
              )}
            </div>
            <p className="text-xs text-t3">
              Leituras de placa — câmeras com módulo ANPR (Hikvision, Intelbras)
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFilters(v => !v)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition',
                showFilters || hasFilters
                  ? 'text-accent border-accent/40 bg-accent/5'
                  : 'text-t2 border-border hover:text-t1',
              )}
            >
              <Filter size={13} />
              Filtros avançados
              {hasFilters && <span className="w-1.5 h-1.5 rounded-full bg-accent" />}
            </button>
            <button onClick={load} className="btn btn-ghost w-8 h-8 p-0" title="Atualizar">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* Filter panel */}
        <div
          className="rounded-xl border p-4 space-y-3"
          style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
        >
          {/* Primary filters — always visible */}
          <div className="flex gap-2 flex-wrap">
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-lg border flex-1 min-w-48"
              style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
            >
              <Search size={13} className="text-t3 shrink-0" />
              <input
                type="text"
                value={plate}
                onChange={e => setPlate(e.target.value.toUpperCase())}
                placeholder="Buscar placa (ex: ABC1234)..."
                className="bg-transparent text-xs text-t1 outline-none flex-1 placeholder:text-t3 font-mono tracking-wider"
              />
              {plate && (
                <button onClick={() => setPlate('')} className="text-t3 hover:text-t1 transition">
                  <X size={11} />
                </button>
              )}
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

          {/* Advanced filters */}
          {showFilters && (
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
                  onClick={() => { setPlate(''); setCameraId(''); setDateFrom(''); setDateTo(''); setConfMin('') }}
                  className="self-end px-3 py-1.5 rounded-lg border text-xs text-t2 hover:text-danger transition"
                  style={{ borderColor: 'var(--border)' }}
                >
                  Limpar filtros
                </button>
              )}
            </div>
          )}
        </div>

        {/* Table */}
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
          <table className="w-full text-sm">
            <thead style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
              <tr>
                <th className="px-3 py-3 w-24" />
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Placa</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Câmera</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Tipo</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Confiança</th>
                <th className="text-left px-4 py-3 text-xs text-t3 font-medium">Horário</th>
                <th className="px-4 py-3 w-24" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                    {[20, 80, 60, 50, 40, 60, 20].map((w, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-3 rounded animate-pulse"
                          style={{ background: 'var(--elevated)', width: `${w}%` }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : displayed.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center gap-3 text-t3">
                      <ScanLine size={36} className="opacity-25" />
                      <span className="text-sm">Nenhuma detecção encontrada</span>
                      {hasFilters && (
                        <button
                          onClick={() => { setPlate(''); setCameraId(''); setDateFrom(''); setDateTo(''); setConfMin('') }}
                          className="text-xs text-accent hover:underline"
                        >
                          Limpar filtros
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ) : displayed.map(ev => {
                const typeColor = getEventTypeColor(ev.event_type)
                return (
                  <tr
                    key={ev.id}
                    style={{ borderBottom: '1px solid var(--border)' }}
                    className="hover:bg-elevated/40 transition-colors"
                  >
                    {/* Thumbnail */}
                    <td className="px-3 py-2">
                      <div
                        className="relative group rounded overflow-hidden"
                        style={{
                          width: 76, height: 48,
                          background: 'var(--elevated)',
                          cursor: ev.image_url ? 'zoom-in' : 'default',
                        }}
                        onClick={() => ev.image_url && setLightboxSrc(ev.image_url)}
                      >
                        {ev.image_url ? (
                          <>
                            <AuthImage
                              src={ev.image_url}
                              alt="snapshot"
                              className="w-full h-full object-cover"
                              style={{ background: 'var(--elevated)' }}
                            />
                            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition flex items-center justify-center opacity-0 group-hover:opacity-100">
                              <ZoomIn size={14} className="text-white drop-shadow" />
                            </div>
                          </>
                        ) : (
                          <div className="w-full h-full flex flex-col items-center justify-center gap-1">
                            <ImageOff size={14} className="text-t3/40" />
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Plate */}
                    <td className="px-4 py-3">
                      {ev.plate ? (
                        <span
                          className="font-mono font-bold text-base text-t1 px-2.5 py-1 rounded-md"
                          style={{
                            background: 'var(--elevated)',
                            border: '1px solid var(--border)',
                            letterSpacing: '0.1em',
                          }}
                        >
                          {ev.plate}
                        </span>
                      ) : (
                        <span className="text-t3 text-xs">—</span>
                      )}
                    </td>

                    {/* Camera */}
                    <td className="px-4 py-3 text-xs text-t1 max-w-36 truncate">
                      {cameraName(ev.camera_id)}
                    </td>

                    {/* Type badge */}
                    <td className="px-4 py-3">
                      <span
                        className="inline-block text-[10px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
                        style={{
                          background: typeColor.bg,
                          color: typeColor.text,
                          border: `1px solid ${typeColor.border}`,
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
        {pages > 1 && (
          <div className="flex items-center justify-between text-xs text-t3">
            <span>
              Página {page} de {pages} · {total.toLocaleString('pt-BR')} registros
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
                onClick={() => setPage(p => Math.min(pages, p + 1))}
                disabled={page >= pages}
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
