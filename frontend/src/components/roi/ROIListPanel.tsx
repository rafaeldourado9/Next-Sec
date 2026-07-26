import { useMemo, useState } from 'react'
import { Plus, Pencil, Trash2, SlidersHorizontal, Camera } from 'lucide-react'
import { clsx } from 'clsx'
import { PLUGIN_NAMES } from '@/constants/plugins'
import { Tooltip } from '@/components/ui/Tooltip'
import type { ROI } from '@/services/analytics'
import type { Camera as CameraType } from '@/types'

interface Props {
  rois: ROI[]
  cameras: CameraType[]
  loading: boolean
  onCreate: () => void
  onEdit: (roi: ROI) => void
  onDelete: (roi: ROI) => void
  onToggleActive: (roi: ROI) => void
  onSelect?: (roi: ROI) => void // Bug 6: handler de seleção
}

export function ROIListPanel({
  rois, cameras, loading, onCreate, onEdit, onDelete, onToggleActive, onSelect,
}: Props) {
  const [filterCamera, setFilterCamera] = useState('all')
  const [filterPlugin, setFilterPlugin] = useState('all')

  const cameraMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of cameras) m.set(c.id, c.name)
    return m
  }, [cameras])

  const filtered = useMemo(() => {
    let list = rois
    if (filterCamera !== 'all') list = list.filter((r) => r.camera_id === filterCamera)
    if (filterPlugin !== 'all') list = list.filter((r) => r.plugin_id === filterPlugin)
    return list
  }, [rois, filterCamera, filterPlugin])

  const grouped = useMemo(() => {
    const map = new Map<string, ROI[]>()
    for (const r of filtered) {
      const arr = map.get(r.camera_id) ?? []
      arr.push(r)
      map.set(r.camera_id, arr)
    }
    return map
  }, [filtered])

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}
      >
        <span className="text-sm font-semibold text-t1">
          ROIs ({filtered.length})
        </span>
        <Tooltip content="Aguarde o carregamento do vídeo para desenhar a zona" placement="bottom">
          <button
            onClick={onCreate}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium text-white transition"
            style={{ background: 'var(--accent)' }}
          >
            <Plus size={13} /> Nova
          </button>
        </Tooltip>
      </div>

      {/* Filters */}
      <div
        className="flex gap-2 px-4 py-2 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}
      >
        <div
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg border flex-1 min-w-0"
          style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
        >
          <Camera size={12} className="text-t3 shrink-0" />
          <select
            value={filterCamera}
            onChange={(e) => setFilterCamera(e.target.value)}
            className="bg-transparent text-xs text-t2 outline-none flex-1 min-w-0"
          >
            <option value="all">Todas cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg border flex-1 min-w-0"
          style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
        >
          <SlidersHorizontal size={12} className="text-t3 shrink-0" />
          <select
            value={filterPlugin}
            onChange={(e) => setFilterPlugin(e.target.value)}
            className="bg-transparent text-xs text-t2 outline-none flex-1 min-w-0"
          >
            <option value="all">Todos plugins</option>
            {Object.entries(PLUGIN_NAMES).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-12 rounded-lg animate-pulse"
                style={{ background: 'var(--elevated)' }}
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <p className="text-sm text-t3 mb-2">Nenhuma ROI configurada</p>
            <p className="text-xs text-t3 mb-4">
              Crie zonas de deteccao para ativar os plugins de analytics nas cameras.
            </p>
            <button
              onClick={onCreate}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white transition"
              style={{ background: 'var(--accent)' }}
            >
              <Plus size={13} /> Criar primeira ROI
            </button>
          </div>
        ) : (
          <div className="py-2">
            {Array.from(grouped.entries()).map(([camId, camRois]) => (
              <div key={camId} className="mb-1">
                {/* Camera group header */}
                <div
                  className="px-4 py-1.5 text-[11px] font-medium text-t3 uppercase tracking-wide"
                  style={{ background: 'var(--surface)' }}
                >
                  {cameraMap.get(camId) ?? camId}
                </div>

                {camRois.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center gap-2 px-4 py-2 hover:bg-elevated/50 transition-colors group cursor-pointer"
                    style={{ borderBottom: '1px solid var(--border)' }}
                    onClick={() => onSelect?.(r)} // Bug 6: clicar na ROI seleciona
                  >
                    {/* Active dot */}
                    <button
                      onClick={() => onToggleActive(r)}
                      title={r.is_active ? 'Ativa' : 'Inativa'}
                      className="shrink-0"
                    >
                      <div
                        className={clsx(
                          'w-2 h-2 rounded-full transition-colors',
                          r.is_active ? 'bg-green-500' : 'bg-gray-500',
                        )}
                      />
                    </button>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-t1 truncate">{r.name}</p>
                      <div className="flex items-center gap-2">
                        <span
                          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                          style={{ background: 'var(--surface)', color: 'var(--text-2)' }}
                        >
                          {PLUGIN_NAMES[r.plugin_id] ?? r.plugin_id}
                        </span>
                        <span className="text-[10px] text-t3">
                          {r.polygon.length} pts
                        </span>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => onEdit(r)}
                        className="p-1 rounded hover:bg-elevated text-t3 hover:text-accent transition"
                        title="Editar"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => onDelete(r)}
                        className="p-1 rounded hover:bg-elevated text-t3 hover:text-red-400 transition"
                        title="Excluir"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
