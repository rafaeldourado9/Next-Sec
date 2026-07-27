import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Settings, Wifi, Edit2, Save, X, ShieldAlert,
  Camera as CameraIcon, Copy, Check, ExternalLink, Eye, EyeOff,
  Download, Radio, Loader2, Plus, Scan, Pencil, Trash2, SlidersHorizontal,
  Brain, ChevronLeft, ChevronRight,
} from 'lucide-react'
import { clsx } from 'clsx'
import { format } from 'date-fns'
import { camerasService } from '@/services/cameras'
import { eventsService } from '@/services/events'
import { analyticsService, type ROI, type AnalyticsCatalogItem } from '@/services/analytics'
import { VideoPlayer } from '@/components/camera/VideoPlayer'
import { PageSpinner } from '@/components/ui/Spinner'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { Confirm } from '@/components/ui/Confirm'
import { usePermission } from '@/hooks/usePermission'
import { useSSE } from '@/hooks/useSSE'
import { getEventTypeLabel, getEventTypeColor, isIntrusionEvent } from '@/constants/eventTypes'
import { PLUGIN_NAMES } from '@/constants/plugins'
import { ROIEditorPanel } from '@/components/roi/ROIEditorPanel'
import { AuthImage } from '@/components/ui/AuthImage'
import type { Camera, VmsEvent } from '@/types'
import toast from 'react-hot-toast'

type Tab = 'live' | 'info' | 'events' | 'analytics'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function maskRtspPassword(url: string | null | undefined): string {
  if (!url) return '—'
  return url.replace(/(rtsp?:\/\/[^:]+:)([^@]+)(@)/, '$1•••$3')
}

function parseLocation(loc: string | null | undefined): { label: string; href: string | null } {
  if (!loc) return { label: 'Não definida', href: null } // Melhoria 12: placeholder em vez de "—"
  try {
    const u = new URL(loc)
    if (u.hostname.includes('google') || u.hostname.includes('goo.gl')) {
      const m = loc.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/) ?? loc.match(/[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)/)
      if (m) return { label: `${parseFloat(m[1]).toFixed(5)}, ${parseFloat(m[2]).toFixed(5)}`, href: loc }
      return { label: 'Ver no mapa', href: loc }
    }
    return { label: u.hostname + (u.pathname !== '/' ? u.pathname : ''), href: loc }
  } catch {
    return { label: loc, href: null }
  }
}

function RtspField({ url }: { url: string | null }) {
  const [show, setShow] = useState(false)
  if (!url) return <p className="text-sm text-t1 mt-1">—</p>
  return (
    <div className="flex items-center gap-2 mt-1">
      <p className="text-sm text-t1 font-mono break-all flex-1">
        {show ? url : maskRtspPassword(url)}
      </p>
      <button
        className="btn btn-ghost w-7 h-7 p-0 shrink-0"
        onClick={() => setShow((s) => !s)}
        title={show ? 'Ocultar senha' : 'Mostrar senha'}
      >
        {show ? <EyeOff size={13} /> : <Eye size={13} />}
      </button>
    </div>
  )
}

function CopyField({ label, value, copyKey, copied, onCopy }: {
  label: string
  value: string
  copyKey: string
  copied: string | null
  onCopy: (v: string, k: string) => void
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex items-center gap-2 mt-1">
        <code className="flex-1 text-xs font-mono rounded-lg px-3 py-2 text-t1 break-all"
          style={{ background: 'var(--elevated)' }}>
          {value}
        </code>
        <button className="btn btn-ghost w-8 h-8 p-0 shrink-0" onClick={() => onCopy(value, copyKey)}
          title="Copiar">
          {copied === copyKey
            ? <Check size={14} style={{ color: 'var(--success)' }} />
            : <Copy size={14} />}
        </button>
      </div>
    </div>
  )
}

function useServerAddress() {
  const isLocalhost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname)
  const [tunnelUrl, setTunnelUrl] = useState<string | null>(null)
  const [timedOut, setTimedOut] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    if (!isLocalhost) return

    let active = true
    let timer: ReturnType<typeof setTimeout>
    const timeout = setTimeout(() => {
      if (active && !tunnelUrl) {
        setTimedOut(true)
      }
    }, 15_000)

    async function poll() {
      try {
        const r = await fetch('/api/v1/system/server-address')
        if (!r.ok) {
          throw new Error(`HTTP ${r.status}`)
        }
        const data: { tunnel_url: string | null } = await r.json()
        if (!active) return
        if (data.tunnel_url) {
          setTunnelUrl(data.tunnel_url)
          setErrorMsg(null)
        } else {
          timer = setTimeout(poll, 3000)
        }
      } catch (err) {
        if (active) {
          setErrorMsg(err instanceof Error ? err.message : 'Erro de rede')
          timer = setTimeout(poll, 3000)
        }
      }
    }

    poll()
    return () => { active = false; clearTimeout(timer); clearTimeout(timeout) }
  }, [isLocalhost])

  if (!isLocalhost) {
    const port = window.location.port
    const portSuffix = port && port !== '80' && port !== '443' ? `:${port}` : ''
    return {
      ready: true,
      baseUrl: `${window.location.protocol}//${window.location.hostname}${portSuffix}`,
      host: window.location.hostname,
      port: port || '80',
      tunnelUrl: null as string | null,
      timedOut: false,
      errorMsg: null,
    }
  }

  if (tunnelUrl) {
    const hostOnly = tunnelUrl.replace(/^https?:\/\//, '').split('/')[0].split(':')[0]
    return { ready: true, baseUrl: tunnelUrl, host: hostOnly, port: '443', tunnelUrl, timedOut: false, errorMsg: null }
  }

  return { ready: false, baseUrl: '', host: '', port: '', tunnelUrl: null, timedOut, errorMsg }
}

function WebhookSection({ camera }: { camera: Camera }) {
  const [copied, setCopied] = useState<string | null>(null)
  const { ready, baseUrl, host, port, tunnelUrl, timedOut, errorMsg } = useServerAddress()
  const isLocalhost = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname)

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  return (
    <div className="mt-6 pt-6 border-t border-border space-y-5">
      <div>
        <p className="text-sm font-semibold text-t1">Configuração de Eventos na Câmera</p>
        <p className="text-xs text-t3 mt-0.5">
          Copie os campos abaixo e cole nas configurações da câmera. Não requer autenticação.
        </p>
      </div>

      {isLocalhost && !ready && !timedOut && (
        <div className="rounded-xl p-3 flex items-center gap-3"
          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)' }}>
          <svg className="animate-spin shrink-0" width={14} height={14} viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={2}>
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          <p className="text-xs text-t3">Obtendo endereço do servidor…</p>
        </div>
      )}

      {isLocalhost && !ready && timedOut && (
        <div className="rounded-xl p-3 space-y-1"
          style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)' }}>
          <div className="flex items-center gap-3">
            <span className="text-xs text-red-400">
              Não foi possível obter o endereço do servidor{errorMsg ? ` (${errorMsg})` : ''}.
            </span>
            <button
              className="text-xs text-accent hover:underline font-medium"
              onClick={() => window.location.reload()}
            >
              Tentar novamente
            </button>
          </div>
          <p className="text-[10px] text-t3">
            Verifique se o container cloudflared está rodando: <code className="text-t2">docker compose --profile dev ps cloudflared</code>
          </p>
        </div>
      )}

      {ready && tunnelUrl && (
        <div className="rounded-xl p-3 space-y-1"
          style={{ background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.25)' }}>
          <p className="text-xs text-green-400 font-medium">Endereço detectado automaticamente</p>
          <p className="text-[11px] text-t3 break-all">{tunnelUrl}</p>
        </div>
      )}

      {ready && camera.manufacturer === 'intelbras' && (
        <div className="rounded-xl border p-4 space-y-3" style={{ borderColor: 'var(--border)' }}>
          <p className="text-xs font-semibold text-t2 uppercase tracking-wide">
            Intelbras — Função Push
          </p>
          <CopyField label='Campo "Cliente"' value={`${baseUrl}/intelbras_events`}
            copyKey="client" copied={copied} onCopy={copy} />
          <CopyField label='Campo "Nº dispos." — identificador desta câmera' value={camera.id}
            copyKey="devid" copied={copied} onCopy={copy} />
          <p className="text-[11px] text-t3 leading-relaxed">
            Em <strong className="text-t2">Função</strong>, marque <strong className="text-t2">Info Placa</strong>.
            Em <strong className="text-t2">Informação de upload</strong>, marque <strong className="text-t2">Nº placa</strong> e <strong className="text-t2">Confiabilidade</strong>.
          </p>
        </div>
      )}

      {ready && camera.manufacturer === 'hikvision' && (
        <div className="rounded-xl border p-4 space-y-3" style={{ borderColor: 'var(--border)' }}>
          <p className="text-xs font-semibold text-t2 uppercase tracking-wide">
            Hikvision — Servidor de Alarme
          </p>
          <CopyField label="IP de destino / Nome do anfitrião" value={host}
            copyKey="hik_host" copied={copied} onCopy={copy} />
          <CopyField label="URL" value={`/hik_pro_connect?camera_id=${camera.id}`}
            copyKey="hik_url" copied={copied} onCopy={copy} />
          <div className="grid grid-cols-2 gap-3">
            <CopyField label="Porta N.º" value={port}
              copyKey="hik_port" copied={copied} onCopy={copy} />
            <div>
              <label className="label">Tipo de protocolo</label>
              <p className="text-xs text-t1 mt-1 px-3 py-2 rounded-lg"
                style={{ background: 'var(--elevated)' }}>HTTP</p>
            </div>
          </div>
        </div>
      )}

      {ready && camera.manufacturer !== 'hikvision' && camera.manufacturer !== 'intelbras' && (
        <div className="rounded-xl border p-4 space-y-3" style={{ borderColor: 'var(--border)' }}>
          <p className="text-xs font-semibold text-t2 uppercase tracking-wide">Endpoint genérico</p>
          <CopyField label="URL completa" value={`${baseUrl}/camera_events?camera_id=${camera.id}`}
            copyKey="gen_url" copied={copied} onCopy={copy} />
        </div>
      )}
    </div>
  )
}

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'live',      label: 'Ao Vivo',     icon: Wifi },
  { id: 'info',      label: 'Informações', icon: Settings },
  { id: 'events',    label: 'Eventos',     icon: ShieldAlert },
  { id: 'analytics', label: 'Analytics',   icon: Scan },
]

export function CameraDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { isAdmin } = usePermission()

  const [tab, setTab]             = useState<Tab>('live')
  const [selectedEvent, setSelectedEvent] = useState<VmsEvent | null>(null)
  const [eventsPage, setEventsPage]   = useState(1)
  const [eventsTotal, setEventsTotal] = useState(0)
  const [camera, setCamera]       = useState<Camera | null>(null)
  const [streamUrl, setStream]    = useState('')
  const [events, setEvents]       = useState<VmsEvent[]>([])
  const [loading, setLoading]     = useState(true)
  const [editing, setEditing]     = useState(false)
  const [editForm, setEditForm]   = useState<Partial<Camera>>({})
  const [saving, setSaving]       = useState(false) // Melhoria 13: loading do botão editar
  const [snapshotOpen, setSnapshotOpen]       = useState(false)
  const [snapshotUrl, setSnapshotUrl]         = useState('')
  const [snapshotLoading, setSnapshotLoading] = useState(false)
  const [snapshotError, setSnapshotError]     = useState(false)

  // ── Analytics / ROIs ──────────────────────────────────────────────────────
  const [rois, setRois]                       = useState<ROI[]>([])
  const [plugins, setPlugins]                 = useState<AnalyticsCatalogItem[]>([])
  const [roisLoading, setRoisLoading]         = useState(false)
  const [roiEditorOpen, setRoiEditorOpen]     = useState(false)
  const [editingRoi, setEditingRoi]           = useState<ROI | null>(null)
  const [deleteRoiTarget, setDeleteRoiTarget] = useState<ROI | null>(null)
  const [deletingRoi, setDeletingRoi]         = useState(false)

  // ── Camera + stream loading ───────────────────────────────────────────────
  useEffect(() => {
    if (!id) return
    Promise.all([
      camerasService.get(id),
      camerasService.streamUrls(id).catch(() => ({ hls_url: '' })),
    ]).then(([cam, urls]) => {
      setCamera(cam)
      setEditForm(cam)
      setStream(urls.hls_url ?? '')
    }).finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    if (!id || tab === 'live' || tab === 'info') return
    if (tab === 'events') {
      eventsService.list({ camera_id: id, page: eventsPage, page_size: 20 })
        .then((r) => { setEvents(r.items ?? []); setEventsTotal(r.total ?? 0) })
    }
    if (tab === 'analytics') {
      setRoisLoading(true)
      Promise.all([
        analyticsService.listROIs(id),
        analyticsService.getCatalog().catch(() => [] as AnalyticsCatalogItem[]),
      ])
        .then(([roiData, catData]) => {
          setRois(roiData)
          setPlugins(catData)
        })
        .catch(() => toast.error('Erro ao carregar ROIs'))
        .finally(() => setRoisLoading(false))
    }
  }, [id, tab, eventsPage])

  // Real-time: recarrega a lista de eventos quando um evento analítico chega
  // por SSE pra essa mesma câmera (só enquanto a aba de eventos tá aberta).
  const { lastEvent } = useSSE()
  const lastSeenRef = useRef<unknown>(null)
  useEffect(() => {
    if (!id || tab !== 'events' || !lastEvent || lastEvent === lastSeenRef.current) return
    lastSeenRef.current = lastEvent
    const inner = (lastEvent as { data?: { event_type?: string; camera_id?: string } }).data
    if (!inner?.event_type?.startsWith('analytics.') || inner.camera_id !== id) return
    eventsService.list({ camera_id: id, page: eventsPage, page_size: 20 })
      .then((r) => { setEvents(r.items ?? []); setEventsTotal(r.total ?? 0) })
  }, [lastEvent, id, tab, eventsPage])

  const handleSave = async () => {
    if (!id || !camera) return
    setSaving(true) // Melhoria 13: loading state
    try {
      const updated = await camerasService.update(id, {
        name:           editForm.name,
        location:       editForm.location ?? undefined,
        retention_days: editForm.retention_days,
      })
      setCamera(updated)
      setEditing(false)
      toast.success('Câmera atualizada')
    } catch { toast.error('Erro ao salvar') }
    finally { setSaving(false) } // Melhoria 13: reset loading
  }

  const openSnapshot = async () => {
    if (!id) return
    setSnapshotUrl('')
    setSnapshotError(false)
    setSnapshotLoading(true)
    setSnapshotOpen(true)
    try {
      const url = await camerasService.snapshot(id)
      if (url) {
        setSnapshotUrl(url)
      } else {
        setSnapshotError(true)
      }
    } catch {
      setSnapshotError(true)
    } finally {
      setSnapshotLoading(false)
    }
  }

  const closeSnapshot = () => {
    setSnapshotOpen(false)
    setSnapshotUrl('')
    setSnapshotError(false)
  }

  const handleRoiSave = () => {
    setRoiEditorOpen(false)
    setEditingRoi(null)
    if (id && tab === 'analytics') {
      setRoisLoading(true)
      analyticsService.listROIs(id)
        .then(setRois)
        .catch(() => toast.error('Erro ao recarregar ROIs'))
        .finally(() => setRoisLoading(false))
    }
  }

  const handleRoiCancel = () => {
    setRoiEditorOpen(false)
    setEditingRoi(null)
  }

  const handleRoiDelete = async () => {
    if (!deleteRoiTarget) return
    setDeletingRoi(true)
    try {
      await analyticsService.deleteROI(deleteRoiTarget.id)
      toast.success('ROI excluída')
      setDeleteRoiTarget(null)
      if (id) {
        setRoisLoading(true)
        analyticsService.listROIs(id)
          .then(setRois)
          .finally(() => setRoisLoading(false))
      }
    } catch {
      toast.error('Erro ao excluir ROI')
    } finally {
      setDeletingRoi(false)
    }
  }

  const handleToggleRoiActive = async (roi: ROI) => {
    try {
      await analyticsService.updateROI(roi.id, {
        camera_id: roi.camera_id,
        plugin_id: roi.plugin_id,
        name: roi.name,
        polygon: roi.polygon,
        config: { ...roi.config, is_active: !roi.is_active },
      })
      setRois((prev) =>
        prev.map((r) => r.id === roi.id ? { ...r, is_active: !r.is_active } : r),
      )
    } catch {
      toast.error('Erro ao atualizar status')
    }
  }

  if (loading) return <PageSpinner />
  if (!camera) return <div className="text-t3 text-center py-16">Câmera não encontrada</div>

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Header + Tabs — pinned, never scrolls */}
      <div className="shrink-0 flex flex-col gap-3 p-3 md:p-4 pb-2">
        {/* Header */}
        <div className="flex items-center gap-3">
        <button className="btn btn-ghost w-8 h-8 p-0" onClick={() => navigate('/cameras')}>
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-base font-semibold text-t1 truncate">{camera.name}</p>
            <Badge variant={camera.is_online ? 'success' : 'danger'} dot>
              {camera.is_online ? 'Online' : 'Offline'}
            </Badge>
          </div>
          <p className="text-xs text-t3 truncate">{parseLocation(camera.location).label}</p>
        </div>
      </div>

        {/* Tabs */}
        <div
          className="flex items-center gap-1 p-1 rounded-xl w-fit"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          {TABS.map(({ id: tid, label, icon: Icon }) => (
            <button
              key={tid}
              onClick={() => setTab(tid)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                tab === tid ? 'text-white' : 'text-t2 hover:text-t1',
              )}
              style={tab === tid ? { background: 'var(--accent)' } : {}}
            >
              <Icon size={14} />{label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab body — scrollable */}
      <div className="flex-1 min-h-0 overflow-auto p-3 md:p-4 pt-0 space-y-4">

      {/* Live */}
      {tab === 'live' && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Player */}
            <div className="lg:col-span-2 space-y-2">
              {/* Live badge */}
              <div className="flex items-center gap-2">
                <span
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold"
                  style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}
                >
                  <Radio size={11} className="animate-pulse" />
                  AO VIVO
                </span>
              </div>

              <VideoPlayer
                src={streamUrl || undefined}
                name={camera.name}
                offline={!camera.is_online}
                className="aspect-video w-full"
                autoPlay
              />
            </div>

            {/* Side panel */}
            <div className="space-y-3">
              <div className="card p-4 space-y-3">
                <p className="text-xs font-semibold text-t2 uppercase tracking-wide">Status</p>
                <div className="space-y-2">
                  {[
                    { label: 'Protocolo',  value: camera.stream_protocol.replace('_', ' ').toUpperCase() },
                    { label: 'Fabricante', value: camera.manufacturer },
                    { label: 'Retenção',   value: `${camera.retention_days} dias` },
                    { label: 'Última vez', value: camera.last_seen_at ? new Date(camera.last_seen_at).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—' },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex justify-between">
                      <span className="text-xs text-t3">{label}</span>
                      <span className="text-xs text-t1 font-medium">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
              <button className="btn btn-ghost w-full gap-2" onClick={openSnapshot}>
                <CameraIcon size={15} />Snapshot
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Snapshot modal */}
      <Modal
        open={snapshotOpen}
        onClose={closeSnapshot}
        title={`Snapshot — ${camera.name}`}
        size="xl"
        footer={snapshotUrl && !snapshotError ? (
          <a
            href={snapshotUrl}
            download={`snapshot_${camera.name.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.jpg`}
            className="btn btn-primary gap-2 text-sm"
          >
            <Download size={14} />Salvar imagem
          </a>
        ) : undefined}
      >
        {snapshotLoading ? (
          <div className="flex items-center justify-center py-10 gap-3 text-t3">
            <div className="w-5 h-5 border-2 border-t-accent rounded-full animate-spin" />
            <span className="text-sm">Capturando snapshot…</span>
          </div>
        ) : snapshotError ? (
          <div className="flex flex-col items-center justify-center py-10 gap-3 text-t3">
            <CameraIcon size={36} className="text-t3/30" />
            <p className="text-sm font-medium">Snapshot indisponível</p>
            <p className="text-xs text-t3/60 text-center max-w-xs">
              A câmera pode estar offline ou não suportar captura de snapshot.
            </p>
          </div>
        ) : snapshotUrl ? (
          <img
            src={snapshotUrl}
            alt="Snapshot"
            className="w-full h-auto rounded-lg object-contain"
            onError={() => setSnapshotError(true)}
          />
        ) : null}
      </Modal>

      {/* Info */}
      {tab === 'info' && (
        <div className="card p-6 max-w-2xl">
          <div className="flex items-center justify-between mb-6">
            <p className="text-sm font-semibold text-t1">Informações da Câmera</p>
            {isAdmin && !editing && (
              <button className="btn btn-ghost gap-2 text-xs" onClick={() => setEditing(true)} disabled={saving}>
                <Edit2 size={14} />Editar
              </button>
            )}
            {editing && (
              <div className="flex gap-2">
                <button className="btn btn-ghost text-xs gap-1" onClick={() => { setEditing(false); setEditForm(camera) }} disabled={saving}>
                  <X size={14} />Cancelar
                </button>
                <button className="btn btn-primary text-xs gap-1" onClick={handleSave} disabled={saving}>
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {saving ? 'Salvando...' : 'Salvar'}
                </button>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {(
              [
                { label: 'Nome',            field: 'name',           type: 'text' },
                {
                  label: 'Localização', field: 'location', type: 'text',
                  viewRender: () => {
                    const { label, href } = parseLocation(camera.location)
                    // Melhoria 12: "Não definida" em cinza claro quando vazio
                    if (!camera.location) return <p className="text-sm text-t3/50 mt-1">{label}</p>
                    if (!href) return <p className="text-sm text-t1 mt-1">{label}</p>
                    return (
                      <a href={href} target="_blank" rel="noopener noreferrer"
                         className="flex items-center gap-1 text-sm text-accent hover:underline mt-1 w-fit">
                        {label}<ExternalLink size={12} />
                      </a>
                    )
                  },
                },
                { label: 'Fabricante',      field: 'manufacturer',   type: 'text' },
                { label: 'Retenção (dias)', field: 'retention_days', type: 'number' },
                {
                  label: 'URL RTSP', field: 'rtsp_url', type: 'text',
                  viewRender: () => <RtspField url={camera.rtsp_url} />,
                },
              ] as { label: string; field: string; type: string; viewRender?: () => React.ReactNode }[]
            ).map(({ label, field, type, viewRender }) => (
              <div key={field}>
                <label className="label">{label}</label>
                {editing ? (
                  <input
                    className="input"
                    type={type}
                    value={(editForm as Record<string, unknown>)[field] as string ?? ''}
                    onChange={(e) => setEditForm((f) => ({
                      ...f,
                      [field]: type === 'number' ? Number(e.target.value) : e.target.value,
                    }))}
                  />
                ) : viewRender ? viewRender() : (
                  <p className="text-sm text-t1 mt-1">{(camera as unknown as Record<string, unknown>)[field] as string ?? '—'}</p>
                )}
              </div>
            ))}
          </div>

          <WebhookSection camera={camera} />
        </div>
      )}

      {/* Events */}
      {tab === 'events' && (
        <>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: 'var(--border)' }}>
                  {['Tipo', 'Placa', 'Data/Hora'].map((h) => (
                    <th key={h} className="px-4 py-3 text-xs font-medium text-t3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {events.map((e) => {
                  const isPlaca = !isIntrusionEvent(e.event_type) && e.plate
                  const typeColor = getEventTypeColor(e.event_type)
                  const hasImage = !!(e.image_url || e.payload.imagem || e.payload.image_b64 || e.payload.foto)
                  return (
                    <tr
                      key={e.id}
                      className="border-b transition cursor-pointer"
                      style={{ borderColor: 'var(--border)' }}
                      onClick={() => setSelectedEvent(e)}
                      onMouseEnter={(el) => { el.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                      onMouseLeave={(el) => { el.currentTarget.style.background = '' }}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span
                            className="inline-block text-[10px] font-medium px-2 py-0.5 rounded-full"
                            style={{ background: typeColor.bg, color: typeColor.text, border: `1px solid ${typeColor.border}` }}
                          >
                            {getEventTypeLabel(e.event_type)}
                          </span>
                          {hasImage && (
                            <span className="text-[9px] text-t3/50">· imagem</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-t2 text-xs font-mono">
                        {isPlaca ? (
                          <span className="font-mono font-bold tracking-widest rounded-md inline-block"
                            style={{ fontSize: 11, padding: '1px 5px', background: '#fff', color: '#18181b', border: '1px solid #d4d4d8' }}>
                            {e.plate}
                          </span>
                        ) : (
                          <span className="inline-block px-2 py-0.5 rounded text-[10px] font-medium"
                            style={{ background: 'rgba(255,255,255,0.06)', color: '#71717a' }}>
                            N/A
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-t3 text-xs">
                        {format(new Date(e.occurred_at), 'dd/MM/yy HH:mm:ss')}
                      </td>
                    </tr>
                  )
                })}
                {events.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-t3 text-sm">Nenhum evento recente</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {eventsTotal > 20 && (() => {
            const pages = Math.ceil(eventsTotal / 20)
            return (
              <div className="flex items-center justify-between px-1">
                <span className="text-[11px] text-t3 tabular-nums">
                  {((eventsPage - 1) * 20 + 1)}–{Math.min(eventsPage * 20, eventsTotal)} de {eventsTotal}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    className="btn btn-ghost text-xs px-2 py-1"
                    disabled={eventsPage === 1}
                    onClick={() => setEventsPage((p) => p - 1)}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  {Array.from({ length: Math.min(pages, 5) }, (_, i) => {
                    const p = eventsPage <= 3 ? i + 1
                      : eventsPage >= pages - 2 ? pages - 4 + i
                      : eventsPage - 2 + i
                    if (p < 1 || p > pages) return null
                    return (
                      <button key={p}
                        className="btn text-xs px-2 py-1"
                        style={p === eventsPage ? { background: 'rgba(59,130,246,0.2)', color: '#60a5fa', border: '1px solid rgba(59,130,246,0.4)' } : {}}
                        onClick={() => setEventsPage(p)}
                      >
                        {p}
                      </button>
                    )
                  })}
                  <button
                    className="btn btn-ghost text-xs px-2 py-1"
                    disabled={eventsPage === pages}
                    onClick={() => setEventsPage((p) => p + 1)}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )
          })()}

          {/* Event preview modal */}
          {selectedEvent && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center p-4"
              style={{ background: 'rgba(0,0,0,0.82)', backdropFilter: 'blur(10px)' }}
              onClick={() => setSelectedEvent(null)}
            >
              <div
                className="w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl flex flex-col"
                style={{ background: 'linear-gradient(180deg, #0e0e16 0%, #0a0a10 100%)', border: '1px solid rgba(255,255,255,0.07)', maxHeight: '85vh' }}
                onClick={(e) => e.stopPropagation()}
              >
                {/* Header */}
                <div className="flex items-center gap-3 px-5 py-3 shrink-0"
                  style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  {selectedEvent.plate ? (
                    <span className="font-mono font-bold tracking-widest rounded-lg"
                      style={{ fontSize: 16, padding: '3px 12px', background: '#fff', color: '#18181b', border: '2px solid #d4d4d8' }}>
                      {selectedEvent.plate}
                    </span>
                  ) : (
                    <span className="text-sm font-semibold text-t1">{getEventTypeLabel(selectedEvent.event_type)}</span>
                  )}
                  <span className="ml-auto text-[11px] text-t3 tabular-nums">
                    {format(new Date(selectedEvent.occurred_at), 'dd/MM/yyyy HH:mm:ss')}
                  </span>
                  <button
                    onClick={() => setSelectedEvent(null)}
                    className="w-7 h-7 flex items-center justify-center rounded-lg transition-colors"
                    style={{ color: '#52525b' }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = '#e4e4e7'; e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = '#52525b'; e.currentTarget.style.background = '' }}
                  >
                    <X size={15} />
                  </button>
                </div>

                {/* Image */}
                {(() => {
                  const imgSrc = selectedEvent.image_url
                    ?? ((selectedEvent.payload.imagem ?? selectedEvent.payload.image_b64 ?? selectedEvent.payload.foto) as string | null | undefined
                        ? `data:image/jpeg;base64,${selectedEvent.payload.imagem ?? selectedEvent.payload.image_b64 ?? selectedEvent.payload.foto}`
                        : null)
                  return imgSrc ? (
                    <div className="shrink-0" style={{ background: '#000' }}>
                      <AuthImage src={imgSrc} alt={selectedEvent.plate ?? 'evento'}
                        className="w-full object-contain" style={{ maxHeight: 340 }} />
                    </div>
                  ) : (
                    <div className="shrink-0 flex flex-col items-center justify-center gap-2"
                      style={{ height: 120, background: '#06060c' }}>
                      <CameraIcon size={32} style={{ color: 'rgba(255,255,255,0.08)' }} />
                      <span className="text-[10px] text-t3/40">Sem imagem</span>
                    </div>
                  )
                })()}

                {/* Details */}
                <div className="px-5 py-4 grid grid-cols-2 gap-x-6 gap-y-3">
                  {[
                    { label: 'Tipo', value: getEventTypeLabel(selectedEvent.event_type) },
                    { label: 'Data/Hora', value: format(new Date(selectedEvent.occurred_at), 'dd/MM/yyyy HH:mm:ss') },
                    ...(selectedEvent.confidence != null ? [{ label: 'Confiança', value: `${Math.round(selectedEvent.confidence * (selectedEvent.confidence > 1 ? 1 : 100))}%` }] : []),
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <p className="text-[10px] text-t3 uppercase tracking-wide mb-0.5">{label}</p>
                      <p className="text-[13px] text-t1 font-medium">{value}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Clips manuais de gravação removidos — Next Sec não tem arquivo de
          gravação contínua para recortar (ver reuse-plan.md). O conceito
          equivalente no Next Sec é o EventClip automático gerado por um
          evento de analytics (ADR-010), não um recorte manual de intervalo. */}

      {/* Analytics / ROIs */}
      {tab === 'analytics' && (
        <div className="space-y-5">
          {/* Header */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Brain size={16} className="text-accent" />
                <p className="text-sm font-semibold text-t1">Analytics</p>
              </div>
              <p className="text-xs text-t3 mt-0.5">Regiões de interesse e detecção por IA</p>
            </div>
            <button
              className="btn btn-primary gap-2 text-xs"
              onClick={() => { setEditingRoi(null); setRoiEditorOpen(true) }}
            >
              <Plus size={13} />Nova ROI
            </button>
          </div>

          {/* Stats summary */}
          {rois.length > 0 && (
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'ROIs Ativas', value: rois.filter(r => r.is_active).length.toString(), color: '#22c55e' },
                { label: 'ROIs Inativas', value: rois.filter(r => !r.is_active).length.toString(), color: '#71717a' },
                { label: 'Plugins', value: new Set(rois.map(r => r.plugin_id)).size.toString(), color: '#3b82f6' },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-xl p-3"
                  style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
                >
                  <p className="text-[10px] text-t3 uppercase tracking-wide">{stat.label}</p>
                  <p className="text-xl font-bold text-t1 mt-1" style={{ color: stat.color }}>{stat.value}</p>
                </div>
              ))}
            </div>
          )}

          {roisLoading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="rounded-xl h-40 animate-pulse" style={{ background: 'var(--elevated)' }} />
              ))}
            </div>
          ) : rois.length === 0 ? (
            <div
              className="rounded-xl p-12 text-center flex flex-col items-center"
              style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
            >
              <div
                className="w-14 h-14 rounded-xl flex items-center justify-center mb-4"
                style={{ background: 'rgba(59,130,246,0.1)' }}
              >
                <SlidersHorizontal size={24} className="text-accent" />
              </div>
              <p className="text-sm font-medium text-t1 mb-1">Nenhuma ROI configurada</p>
              <p className="text-xs text-t3 mb-4 max-w-xs">
                Crie uma região de interesse para começar a detectar eventos com IA nesta câmera.
              </p>
              <button
                className="btn btn-primary gap-2 text-xs"
                onClick={() => { setEditingRoi(null); setRoiEditorOpen(true) }}
              >
                <Plus size={14} />Criar primeira ROI
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {rois.map((r) => (
                <div
                  key={r.id}
                  className="rounded-xl overflow-hidden transition-all hover:scale-[1.01]"
                  style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
                >
                  {/* Preview */}
                  <div className="relative h-32 overflow-hidden" style={{ background: '#05050a' }}>
                    <svg
                      viewBox="0 0 100 100"
                      className="w-full h-full"
                      preserveAspectRatio="none"
                    >
                      {r.polygon.length > 2 && (
                        <polygon
                          points={r.polygon.map(p => `${p[0] * 100},${p[1] * 100}`).join(' ')}
                          fill="rgba(59,130,246,0.2)"
                          stroke="#3b82f6"
                          strokeWidth="0.5"
                        />
                      )}
                      {r.polygon.map((p, i) => (
                        <circle
                          key={i}
                          cx={p[0] * 100}
                          cy={p[1] * 100}
                          r="1.5"
                          fill="#3b82f6"
                        />
                      ))}
                    </svg>
                    <div className="absolute top-2 left-2">
                      <div
                        className={clsx(
                          'w-2 h-2 rounded-full',
                          r.is_active ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-gray-500'
                        )}
                      />
                    </div>
                    <div className="absolute top-2 right-2">
                      <span
                        className="text-[9px] font-medium px-2 py-0.5 rounded-full"
                        style={{
                          background: 'rgba(0,0,0,0.6)',
                          color: '#fff',
                          backdropFilter: 'blur(4px)',
                        }}
                      >
                        {r.polygon.length} pts
                      </span>
                    </div>
                  </div>

                  {/* Info */}
                  <div className="p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-t1 truncate">{r.name}</p>
                        <p className="text-[11px] text-t3 mt-0.5">
                          {PLUGIN_NAMES[r.plugin_id] ?? r.plugin_id}
                        </p>
                      </div>
                      <div className="flex items-center gap-0.5 shrink-0">
                        <button
                          onClick={() => handleToggleRoiActive(r)}
                          className={clsx(
                            'p-1.5 rounded-lg transition',
                            r.is_active ? 'text-green-400 hover:bg-green-400/10' : 'text-t3 hover:bg-elevated hover:text-t2'
                          )}
                          title={r.is_active ? 'Desativar' : 'Ativar'}
                        >
                          {r.is_active ? <Eye size={14} /> : <EyeOff size={14} />}
                        </button>
                        <button
                          onClick={() => { setEditingRoi(r); setRoiEditorOpen(true) }}
                          className="p-1.5 rounded-lg text-t3 hover:bg-elevated hover:text-accent transition"
                          title="Editar"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => setDeleteRoiTarget(r)}
                          className="p-1.5 rounded-lg text-t3 hover:bg-elevated hover:text-red-400 transition"
                          title="Excluir"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>

                    {/* Config badges */}
                    {Object.entries(r.config).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {Object.entries(r.config).slice(0, 3).map(([key, val]) => (
                          <span
                            key={key}
                            className="text-[9px] px-1.5 py-0.5 rounded"
                            style={{ background: 'var(--elevated)', color: 'var(--text-3)' }}
                          >
                            {key}: {String(val)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}{/* end analytics */}
      </div>{/* end tab body */}

      {/* ROI Editor Modal */}
      <Modal
        open={roiEditorOpen}
        onClose={handleRoiCancel}
        title={editingRoi ? 'Editar ROI' : 'Nova ROI'}
        size="full"
      >
        <div className="h-[70vh]">
          <ROIEditorPanel
            key={editingRoi ? `edit-${editingRoi.id}` : 'create'}
            roi={editingRoi ?? undefined}
            cameras={camera ? [camera] : []}
            plugins={plugins}
            onSave={handleRoiSave}
            onCancel={handleRoiCancel}
            defaultCameraId={camera?.id}
          />
        </div>
      </Modal>

      {/* Delete ROI confirmation */}
      <Confirm
        open={!!deleteRoiTarget}
        message={`Excluir a ROI "${deleteRoiTarget?.name}"? Esta ação não pode ser desfeita.`}
        onConfirm={handleRoiDelete}
        onCancel={() => setDeleteRoiTarget(null)}
        loading={deletingRoi}
      />
    </div>
  )
}
