import { useCallback, useEffect, useState } from 'react'
import { Scan, Focus } from 'lucide-react'
import { analyticsService, type ROI, type AnalyticsCatalogItem } from '@/services/analytics'
import { camerasService } from '@/services/cameras'
import { ROIListPanel } from '@/components/roi/ROIListPanel'
import { ROIEditorPanel } from '@/components/roi/ROIEditorPanel'
import { Confirm } from '@/components/ui/Confirm'
import type { Camera } from '@/types'
import toast from 'react-hot-toast'

type EditorMode = 'closed' | 'create' | 'edit'

export function ROIManagementPage() {
  const [rois, setRois] = useState<ROI[]>([])
  const [cameras, setCameras] = useState<Camera[]>([])
  const [plugins, setPlugins] = useState<AnalyticsCatalogItem[]>([])
  const [loading, setLoading] = useState(true)

  const [editorMode, setEditorMode] = useState<EditorMode>('closed')
  const [editingRoi, setEditingRoi] = useState<ROI | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<ROI | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadData = useCallback(async () => {
    try {
      const [roiData, camData, catData] = await Promise.all([
        analyticsService.listROIs(),
        camerasService.list(),
        analyticsService.getCatalog().catch(() => [] as AnalyticsCatalogItem[]),
      ])
      setRois(roiData)
      setCameras(camData)
      setPlugins(catData)
    } catch {
      toast.error('Erro ao carregar dados')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleCreate = () => {
    setEditingRoi(null)
    setEditorMode('create')
  }

  const handleEdit = (roi: ROI) => {
    setEditingRoi(roi)
    setEditorMode('edit')
  }

  const handleSave = () => {
    setEditorMode('closed')
    setEditingRoi(null)
    loadData()
  }

  const handleCancel = () => {
    setEditorMode('closed')
    setEditingRoi(null)
  }

  const handleToggleActive = async (roi: ROI) => {
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

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await analyticsService.deleteROI(deleteTarget.id)
      toast.success('ROI excluida')
      setDeleteTarget(null)
      loadData()
    } catch {
      toast.error('Erro ao excluir ROI')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Page header */}
      <div
        className="px-6 py-4 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-2.5 mb-1">
          <Scan size={20} className="text-accent" />
          <h1 className="text-xl font-bold text-t1">Regioes de Interesse</h1>
        </div>
        <p className="text-xs text-t3">
          Configure as zonas de deteccao para os plugins de analytics nas cameras.
        </p>
      </div>

      {/* Split layout */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Left — list */}
        <div
          className="w-[360px] shrink-0 border-r overflow-hidden"
          style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
        >
          <ROIListPanel
            rois={rois}
            cameras={cameras}
            loading={loading}
            onCreate={handleCreate}
            onEdit={handleEdit}
            onDelete={setDeleteTarget}
            onToggleActive={handleToggleActive}
            onSelect={handleEdit} // Bug 6: clicar na ROI abre editor
          />
        </div>

          {/* Right — editor or placeholder */}
          <div className="flex-1 overflow-hidden" style={{ background: 'var(--background)' }}>
            {editorMode !== 'closed' ? (
              // Bug 6: key força re-mount ao trocar entre create/edit, garantindo estado limpo
              <ROIEditorPanel
                key={editorMode === 'create' ? 'create' : `edit-${editingRoi?.id}`}
                roi={editingRoi ?? undefined}
                cameras={cameras}
                plugins={plugins}
                onSave={handleSave}
                onCancel={handleCancel}
              />
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-center px-8">
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
                style={{ background: 'var(--elevated)' }}
              >
                <Focus size={28} className="text-t3" />
              </div>
              <p className="text-sm text-t2 mb-1">Selecione ou crie uma ROI</p>
              <p className="text-xs text-t3 max-w-xs">
                Escolha uma ROI existente na lista para editar, ou clique em "Nova" para criar uma zona de deteccao.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation */}
      <Confirm
        open={!!deleteTarget}
        message={`Excluir a ROI "${deleteTarget?.name}"? Esta acao nao pode ser desfeita.`}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        loading={deleting}
      />
    </div>
  )
}
