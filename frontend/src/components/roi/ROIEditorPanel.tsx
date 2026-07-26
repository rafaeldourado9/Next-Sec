import { useEffect, useState } from 'react'
import { X, Save, Loader2 } from 'lucide-react'
import { analyticsService, type ROI, type AnalyticsCatalogItem } from '@/services/analytics'
import { PLUGIN_NAMES } from '@/constants/plugins'
import { POLYGON_REQUIRED, PLUGIN_CONFIG_SCHEMA } from '@/constants/pluginConfigs'
import { PolygonEditor } from './PolygonEditor'
import { PluginConfigForm } from './PluginConfigForm'
import { camerasService } from '@/services/cameras'
import type { Camera } from '@/types'
import toast from 'react-hot-toast'

interface Props {
  roi?: ROI
  cameras: Camera[]
  plugins: AnalyticsCatalogItem[]
  onSave: () => void
  onCancel: () => void
  defaultCameraId?: string
}

export function ROIEditorPanel({ roi, cameras, plugins, onSave, onCancel, defaultCameraId }: Props) {
  const isEdit = !!roi

  const [cameraId, setCameraId] = useState(roi?.camera_id ?? defaultCameraId ?? '')
  const [pluginId, setPluginId] = useState(roi?.plugin_id ?? '')
  const [name, setName] = useState(roi?.name ?? '')
  const [polygon, setPolygon] = useState(roi?.polygon ?? [])
  const [config, setConfig] = useState(roi?.config ?? {})
  const [saving, setSaving] = useState(false)
  const [streamUrl, setStreamUrl] = useState<string | null>(null)
  const [streamReady, setStreamReady] = useState(false) // Bug 5: controle de carregamento do stream

  // Bug 6: sincroniza estado quando a ROI selecionada muda; reseta ao entrar em modo criação
  useEffect(() => {
    if (roi) {
      setCameraId(roi.camera_id)
      setPluginId(roi.plugin_id)
      setName(roi.name)
      setPolygon(roi.polygon)
      setConfig(roi.config ?? {})
    } else {
      // Modo criação: reseta formulário para valores padrão
      setCameraId(defaultCameraId ?? '')
      setPluginId('')
      setName('')
      setPolygon([])
      setConfig({})
    }
  }, [roi?.id, defaultCameraId])

  useEffect(() => {
    if (!cameraId) { setStreamUrl(null); setStreamReady(false); return }
    setStreamReady(false) // Bug 5: reset ao trocar câmera
    camerasService.streamUrls(cameraId)
      .then((s) => {
        setStreamUrl(s.hls_url || null)
        setStreamReady(!!s.hls_url) // Bug 5: stream pronto quando URL existe
      })
      .catch(() => { setStreamUrl(null); setStreamReady(false) })
  }, [cameraId])

  // Ao trocar plugin, reseta config com defaults
  useEffect(() => {
    if (isEdit) return
    const schema = PLUGIN_CONFIG_SCHEMA[pluginId] ?? []
    const defaults: Record<string, unknown> = {}
    for (const f of schema) {
      defaults[f.key] = f.default
    }
    setConfig(defaults)
  }, [pluginId, isEdit])

  const canSave = () => {
    if (!cameraId || !pluginId || !name.trim()) return false
    if (POLYGON_REQUIRED[pluginId] && polygon.length < 3) return false
    return true
  }

  const handleSave = async () => {
    if (!canSave()) return
    setSaving(true)
    try {
      const payload = {
        camera_id: cameraId,
        plugin_id: pluginId,
        name: name.trim(),
        polygon,
        config,
      }
      if (isEdit && roi) {
        await analyticsService.updateROI(roi.id, payload)
        toast.success('ROI atualizada')
      } else {
        await analyticsService.createROI(payload)
        toast.success('ROI criada')
      }
      onSave()
    } catch {
      toast.error('Erro ao salvar ROI')
    } finally {
      setSaving(false)
    }
  }

  const availablePlugins = plugins.length > 0
    ? plugins
    : Object.entries(PLUGIN_NAMES).map(([id, n]) => ({ id, name: n }))

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}
      >
        <h2 className="text-sm font-semibold text-t1">
          {isEdit ? 'Editar ROI' : 'Nova ROI'}
        </h2>
        <button onClick={onCancel} className="text-t3 hover:text-t1 transition">
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Camera — hide when locked to a single camera */}
        {cameras.length > 1 && (
          <div>
            <label className="text-xs text-t3 mb-1 block">Camera</label>
            <select
              value={cameraId}
              onChange={(e) => { setCameraId(e.target.value); setPolygon([]) }}
              disabled={isEdit}
              className="w-full px-3 py-1.5 rounded-lg border text-sm text-t1 outline-none focus:border-accent/60 transition"
              style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
            >
              <option value="">Selecione uma camera</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
        )}

        {/* Plugin */}
        <div>
          <label className="text-xs text-t3 mb-1 block">Plugin</label>
          <select
            value={pluginId}
            onChange={(e) => setPluginId(e.target.value)}
            disabled={isEdit}
            className="w-full px-3 py-1.5 rounded-lg border text-sm text-t1 outline-none focus:border-accent/60 transition"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
          >
            <option value="">Selecione um plugin</option>
            {availablePlugins.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* Name */}
        <div>
          <label className="text-xs text-t3 mb-1 block">Nome da ROI</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ex: Entrada principal"
            className="w-full px-3 py-1.5 rounded-lg border text-sm text-t1 outline-none focus:border-accent/60 transition"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
          />
        </div>

        {/* Polygon editor — Bug 5: skeleton loader + tools desabilitados até stream pronto */}
        {cameraId && (
          <div>
            <label className="text-xs text-t3 mb-1 block">
              Zona de deteccao
              {pluginId && POLYGON_REQUIRED[pluginId] && (
                <span className="text-red-400 ml-1">*</span>
              )}
              {pluginId && !POLYGON_REQUIRED[pluginId] && (
                <span className="text-t3 ml-1">(opcional)</span>
              )}
              {!streamReady && POLYGON_REQUIRED[pluginId] && (
                <span className="text-t3 ml-1 inline-flex items-center gap-1">
                  <Loader2 size={10} className="animate-spin" />
                  Aguardando vídeo...
                </span>
              )}
            </label>
            {!streamReady ? (
              // Bug 5: skeleton loader enquanto stream não está pronto
              <div
                className="w-full aspect-video rounded-lg animate-pulse"
                style={{ background: 'var(--elevated)' }}
              />
            ) : (
              <PolygonEditor
                cameraId={cameraId}
                polygon={polygon}
                onChange={setPolygon}
                streamUrl={streamUrl ?? undefined}
                disabled={!streamReady} // Bug 5: desabilita ferramentas até carregamento
              />
            )}
          </div>
        )}

        {/* Plugin config */}
        {pluginId && (
          <div>
            <label className="text-xs text-t3 mb-2 block">Configuracao do plugin</label>
            <PluginConfigForm
              pluginId={pluginId}
              config={config}
              onChange={setConfig}
            />
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        className="flex items-center justify-end gap-2 px-4 py-3 border-t shrink-0"
        style={{ borderColor: 'var(--border)' }}
      >
        <button
          onClick={onCancel}
          className="px-3 py-1.5 rounded-lg text-xs font-medium text-t2 hover:text-t1 transition"
          style={{ background: 'var(--elevated)' }}
        >
          Cancelar
        </button>
        <button
          onClick={handleSave}
          disabled={!canSave() || saving}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white transition disabled:opacity-40"
          style={{ background: 'var(--accent)' }}
        >
          <Save size={13} />
          {saving ? 'Salvando...' : 'Salvar'}
        </button>
      </div>
    </div>
  )
}
