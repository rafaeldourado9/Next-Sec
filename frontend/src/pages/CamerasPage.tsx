import { useEffect, useMemo, useState } from 'react'
import {
  Plus, Search, MoreVertical, Trash2, ExternalLink,
  Camera as CameraIcon, Wifi, Eye, Globe,
  ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { camerasService } from '@/services/cameras'
import { AddCameraWizard } from '@/components/wizard/AddCameraWizard'
import { Thumbnail } from '@/components/camera/Thumbnail'
import { usePermission } from '@/hooks/usePermission'
import { useSSE } from '@/hooks/useSSE'
import { useCameraStore } from '@/store/cameraStore'
import toast from 'react-hot-toast'
import type { Camera } from '@/types'

type FilterStatus = 'all' | 'online' | 'offline'

const PROTOCOL_LABELS: Record<string, { label: string; Icon: typeof Wifi }> = {
  rtsp_pull: { label: 'RTSP',  Icon: Globe },
  rtmp_push: { label: 'RTMP',  Icon: Wifi  },
  onvif:     { label: 'ONVIF', Icon: Eye   },
}

const MANUFACTURER_LABELS: Record<string, string> = {
  hikvision: 'Hikvision',
  intelbras: 'Intelbras',
  generic:   'Genérica',
}

const PAGE_SIZE = 10

export function CamerasPage() {
  const navigate    = useNavigate()
  const { isAdmin } = usePermission()

  const [cameras,  setCameras]  = useState<Camera[]>([])
  const [loading,  setLoading]  = useState(true)
  const [search,   setSearch]   = useState('')
  const [filter,   setFilter]   = useState<FilterStatus>('all')
  const [showAdd,  setShowAdd]  = useState(false)
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const [page,     setPage]     = useState(1)

  const { lastEvent } = useSSE()
  const setOnline   = useCameraStore((s) => s.setOnline)
  const setOffline  = useCameraStore((s) => s.setOffline)
  const sseStatuses = useCameraStore((s) => s.cameras)

  useEffect(() => {
    if (!lastEvent) return
    const type     = lastEvent.type as string | undefined
    const cameraId = lastEvent.camera_id as string | undefined
    if (!cameraId) return
    if (type === 'camera.online') {
      setOnline(cameraId)
      setCameras((prev) => prev.map((c) => c.id === cameraId ? { ...c, is_online: true } : c))
    }
    if (type === 'camera.offline') {
      setOffline(cameraId)
      setCameras((prev) => prev.map((c) => c.id === cameraId ? { ...c, is_online: false } : c))
    }
  }, [lastEvent, setOnline, setOffline])

  const load = () => {
    setLoading(true)
    camerasService.list({ page_size: 200 })
      .then((cams) => {
        const merged = cams.map((c) =>
          c.id in sseStatuses ? { ...c, is_online: sseStatuses[c.id].online } : c,
        )
        setCameras(merged)
        setPage(1) // Volta para primeira página ao recarregar
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const filtered = useMemo(() => {
    return cameras.filter((c) => {
      if (filter === 'online'  && !c.is_online) return false
      if (filter === 'offline' &&  c.is_online) return false
      if (search && !c.name.toLowerCase().includes(search.toLowerCase()) &&
          !(c.location ?? '').toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [cameras, filter, search])

  // Paginação
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const paginated = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE
    return filtered.slice(start, start + PAGE_SIZE)
  }, [filtered, safePage])

  // Reseta para página 1 ao mudar filtro/busca
  useEffect(() => { setPage(1) }, [search, filter])

  const handleDelete = async (cam: Camera) => {
    if (!confirm(`Remover câmera "${cam.name}"?`)) return
    try {
      await camerasService.del(cam.id)
      toast.success('Câmera removida')
      setMenuOpen(null)
      load()
    } catch { toast.error('Erro ao remover câmera') }
  }

  const onlineCount  = cameras.filter((c) =>  c.is_online).length
  const offlineCount = cameras.filter((c) => !c.is_online).length

  useEffect(() => {
    if (!menuOpen) return
    const handler = () => setMenuOpen(null)
    window.addEventListener('click', handler, { once: true })
    return () => window.removeEventListener('click', handler)
  }, [menuOpen])

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-48 max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-t3 pointer-events-none" />
          <input
            className="input pl-9"
            placeholder="Buscar câmeras..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Filter pills */}
        <div className="flex items-center gap-1.5">
          {([
            { key: 'all'     as FilterStatus, label: 'Todas',  count: cameras.length },
            { key: 'online'  as FilterStatus, label: 'Online',  count: onlineCount,  dot: 'bg-green-500' },
            { key: 'offline' as FilterStatus, label: 'Offline', count: offlineCount, dot: 'bg-red-500'   },
          ]).map(({ key, label, count, dot }) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border',
                filter === key
                  ? 'text-white border-transparent'
                  : 'text-t2 border-border hover:text-t1 hover:bg-elevated',
              )}
              style={filter === key ? { background: 'var(--accent)', borderColor: 'var(--accent)' } : {}}
            >
              {dot && <span className={clsx('w-1.5 h-1.5 rounded-full', dot)} />}
              {label}
              <span className={clsx('tabular-nums', filter === key ? 'text-white/70' : 'text-t3')}>
                {count}
              </span>
            </button>
          ))}
        </div>

        {isAdmin && (
          <button onClick={() => setShowAdd(true)} className="btn btn-primary ml-auto">
            <Plus size={15} />Nova Câmera
          </button>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-24">
          <div className="flex flex-col items-center gap-3 text-t3 text-sm">
            <div
              className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
              style={{ borderColor: 'var(--accent) var(--accent) transparent transparent' }}
            />
            <span>Carregando câmeras...</span>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <CameraIcon size={28} className="text-t3" />
          </div>
          <p className="text-sm text-t1 font-medium mb-1">Nenhuma câmera encontrada</p>
          <p className="text-xs text-t3">
            {cameras.length === 0 ? 'Adicione sua primeira câmera' : 'Tente ajustar os filtros'}
          </p>
          {isAdmin && cameras.length === 0 && (
            <button onClick={() => setShowAdd(true)} className="btn btn-primary mt-4">
              <Plus size={15} />Adicionar Câmera
            </button>
          )}
        </div>
      ) : (
        <>
          <div
            className="rounded-xl border"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
          >
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['', 'Nome', 'Localização', 'Protocolo', 'Fabricante', 'Qualidade', 'Retenção', 'Status', ''].map((h, i) => (
                    <th
                      key={i}
                      className={clsx(
                        'px-4 py-3 text-xs font-medium text-t3 uppercase tracking-wider',
                        h === '' ? 'w-20' : 'text-left',
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginated.map((cam) => {
                  const proto = PROTOCOL_LABELS[cam.stream_protocol]
                  return (
                    <tr
                      key={cam.id}
                      className="group border-b transition-colors hover:bg-elevated/50 cursor-pointer last:border-b-0"
                      style={{ borderColor: 'var(--border)' }}
                      onClick={() => navigate(`/cameras/${cam.id}`)}
                    >
                      {/* Thumbnail com lazy loading */}
                      <td className="px-3 py-2">
                        <div
                          className="w-16 h-10 rounded-lg overflow-hidden"
                          style={{ background: 'var(--elevated)' }}
                        >
                          <Thumbnail cameraId={cam.id} className="w-full h-full" />
                        </div>
                      </td>

                      {/* Nome + status dot */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span
                            className={clsx(
                              'w-2 h-2 rounded-full ring-2 shrink-0',
                              cam.is_online
                                ? 'bg-green-500 ring-green-500/20'
                                : 'bg-red-500 ring-red-500/20',
                            )}
                          />
                          <p className="font-medium text-t1 truncate max-w-[220px]">{cam.name}</p>
                        </div>
                      </td>

                      {/* Localização */}
                      <td className="px-4 py-3">
                        <span className="text-t2 text-xs truncate block max-w-[180px]">
                          {cam.location ?? <span className="text-t3">—</span>}
                        </span>
                      </td>

                      {/* Protocolo */}
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-elevated text-t2">
                          {proto && <proto.Icon size={11} />}
                          {proto?.label ?? cam.stream_protocol}
                        </span>
                      </td>

                      {/* Fabricante */}
                      <td className="px-4 py-3 text-t3 text-xs">
                        {MANUFACTURER_LABELS[cam.manufacturer] ?? cam.manufacturer}
                      </td>

                      {/* Qualidade */}
                      <td className="px-4 py-3">
                        <span className="text-xs text-t3 uppercase tracking-wide">
                          {cam.stream_quality ?? 'high'}
                        </span>
                      </td>

                      {/* Retenção */}
                      <td className="px-4 py-3 text-t3 text-xs">{cam.retention_days}d</td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        {cam.is_online
                          ? <span className="text-green-500 text-xs font-medium">Online</span>
                          : <span className="text-t3 text-xs">Offline</span>}
                      </td>

                      {/* Ações */}
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-0.5">
                          <button
                            onClick={(e) => { e.stopPropagation(); navigate(`/cameras/${cam.id}`) }}
                            className="p-1.5 rounded-md text-t3 hover:text-t1 hover:bg-elevated transition"
                            title="Detalhes"
                          >
                            <ExternalLink size={13} />
                          </button>
                          {isAdmin && (
                            <div className="relative" onClick={(e) => e.stopPropagation()}>
                              <button
                                onClick={() => setMenuOpen(menuOpen === cam.id ? null : cam.id)}
                                className="p-1.5 rounded-md text-t3 hover:text-t1 hover:bg-elevated transition"
                                title="Mais opções"
                              >
                                <MoreVertical size={13} />
                              </button>
                              {menuOpen === cam.id && (
                                <div
                                  className="absolute right-0 top-8 z-50 min-w-[140px] rounded-xl border shadow-xl py-1"
                                  style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
                                >
                                  <button
                                    onClick={() => handleDelete(cam)}
                                    className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-red-500/10 transition"
                                    style={{ color: 'var(--danger)' }}
                                  >
                                    <Trash2 size={12} />Remover
                                  </button>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Paginação */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-t3">
                Mostrando {((safePage - 1) * PAGE_SIZE) + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} de {filtered.length}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(1)}
                  disabled={safePage === 1}
                  className="p-1.5 rounded-md text-t3 hover:text-t1 hover:bg-elevated transition disabled:opacity-30 disabled:cursor-not-allowed"
                  title="Primeira página"
                >
                  <ChevronsLeft size={14} />
                </button>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={safePage === 1}
                  className="p-1.5 rounded-md text-t3 hover:text-t1 hover:bg-elevated transition disabled:opacity-30 disabled:cursor-not-allowed"
                  title="Página anterior"
                >
                  <ChevronLeft size={14} />
                </button>

                {/* Page numbers */}
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={clsx(
                      'min-w-[28px] h-7 rounded-md text-xs font-medium transition',
                      p === safePage
                        ? 'text-white'
                        : 'text-t3 hover:text-t1 hover:bg-elevated',
                    )}
                    style={p === safePage ? { background: 'var(--accent)' } : {}}
                  >
                    {p}
                  </button>
                ))}

                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={safePage === totalPages}
                  className="p-1.5 rounded-md text-t3 hover:text-t1 hover:bg-elevated transition disabled:opacity-30 disabled:cursor-not-allowed"
                  title="Próxima página"
                >
                  <ChevronRight size={14} />
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={safePage === totalPages}
                  className="p-1.5 rounded-md text-t3 hover:text-t1 hover:bg-elevated transition disabled:opacity-30 disabled:cursor-not-allowed"
                  title="Última página"
                >
                  <ChevronsRight size={14} />
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <AddCameraWizard
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={() => { setShowAdd(false); load() }}
      />
    </div>
  )
}
