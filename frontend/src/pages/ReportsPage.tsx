import { useEffect, useState, useCallback } from 'react'
import { FileText, Download, Plus, RefreshCw, Clock, CheckCircle, XCircle, Loader2, Radio, Bell, Search, Brain } from 'lucide-react'
import { format } from 'date-fns'
import { reportsService, type ReportItem } from '@/services/reports'
import { PageSpinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import { Badge } from '@/components/ui/Badge'
import toast from 'react-hot-toast'

const REPORT_TYPES: Record<string, { label: string; icon: React.ElementType }> = {
  cameras_status:        { label: 'Status de Câmeras',       icon: Radio },
  events_summary:        { label: 'Resumo de Eventos',        icon: Bell },
  audit_trail:           { label: 'Trilha de Auditoria',      icon: Search },
  analytics_events:      { label: 'Eventos de Analytics',     icon: Brain },
}

const STATUS_CONFIG: Record<string, { color: string; bg: string; label: string; Icon: React.ElementType }> = {
  pending:   { color: '#f59e0b', bg: '#f59e0b18', label: 'Pendente',   Icon: Clock },
  processing:{ color: '#3b82f6', bg: '#3b82f618', label: 'Gerando',    Icon: Loader2 },
  ready:     { color: '#22c55e', bg: '#22c55e18', label: 'Pronto',     Icon: CheckCircle },
  failed:    { color: '#ef4444', bg: '#ef444418', label: 'Falhou',     Icon: XCircle },
}

const PAGE_SIZE = 20

export function ReportsPage() {
  const [reports, setReports] = useState<ReportItem[]>([])
  const [loading, setLoading]   = useState(true)
  const [page, setPage]         = useState(1)
  const [total, setTotal]       = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [selectedType, setSelectedType] = useState('events_summary')
  const [creating, setCreating] = useState(false)

  const load = useCallback((p: number) => {
    setLoading(true)
    reportsService.list(p, PAGE_SIZE)
      .then((r) => { setReports(r.items); setTotal(r.total) })
      .catch(() => setReports([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(page) }, [page])

  const handleCreate = async () => {
    setCreating(true)
    try {
      const report = await reportsService.create(selectedType, { period_days: 7 })
      toast.success(`Relatório "${REPORT_TYPES[selectedType]?.label ?? selectedType}" solicitado`)
      setShowCreate(false)
      // Polling: esperar 2s e verificar se ficou pronto
      setTimeout(async () => {
        const updated = await reportsService.get(report.id)
        if (updated.status === 'ready') {
          toast.success('Relatório pronto para download!')
          load(1)
        } else {
          load(1)
        }
      }, 2000)
      load(1)
    } catch {
      toast.error('Erro ao solicitar relatório')
    } finally {
      setCreating(false)
    }
  }

  const handleDownload = (report: ReportItem) => {
    if (!report.file_path) {
      toast.error('Relatório não disponível')
      return
    }
    reportsService.download(report.id)
    toast.success('Download iniciado')
  }

  const handleGenerateNow = async (report: ReportItem) => {
    try {
      toast.loading('Gerando relatório...', { id: `gen-${report.id}` })
      await reportsService.generateNow(report.id)
      toast.success('Relatório gerado!', { id: `gen-${report.id}` })
      load(page)
    } catch {
      toast.error('Erro ao gerar relatório', { id: `gen-${report.id}` })
    }
  }

  const pages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-t1">Relatórios</p>
          <p className="text-xs text-t3 mt-0.5">Gere e baixe relatórios em PDF</p>
        </div>
        <button className="btn btn-primary gap-2" onClick={() => setShowCreate(true)}>
          <Plus size={16} />Novo Relatório
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <PageSpinner />
        ) : reports.length === 0 ? (
          <div className="py-16 text-center text-sm text-t3">
            <FileText size={32} className="mx-auto mb-3 opacity-30" />
            Nenhum relatório gerado ainda
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: 'var(--border)' }}>
                  {['Tipo', 'Status', 'Gerado em', 'Ações'].map((h) => (
                    <th key={h} className="px-4 py-3 text-xs font-medium text-t3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => {
                  const typeInfo = REPORT_TYPES[r.report_type] ?? { label: r.report_type, icon: FileText }
                  const statusCfg = STATUS_CONFIG[r.status] ?? STATUS_CONFIG.pending

                  return (
                    <tr key={r.id} className="border-b hover:bg-elevated transition" style={{ borderColor: 'var(--border)' }}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <typeInfo.icon size={18} className="text-t3 shrink-0" />
                          <div>
                            <p className="text-sm font-medium text-t1">{typeInfo.label}</p>
                            <p className="text-xs text-t3 font-mono">{r.id.slice(0, 8)}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={r.status === 'ready' ? 'success' : r.status === 'failed' ? 'danger' : 'default'}
                          dot
                        >
                          {statusCfg.label}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-t3 tabular-nums">
                        {r.generated_at
                          ? format(new Date(r.generated_at), 'dd/MM/yy HH:mm')
                          : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {r.status === 'ready' ? (
                            <button
                              className="btn btn-ghost text-xs gap-1.5"
                              onClick={() => handleDownload(r)}
                            >
                              <Download size={13} /> Download
                            </button>
                          ) : r.status === 'pending' ? (
                            <button
                              className="btn btn-ghost text-xs gap-1.5"
                              onClick={() => handleGenerateNow(r)}
                            >
                              <RefreshCw size={13} /> Gerar agora
                            </button>
                          ) : (
                            <span className="text-xs text-t3">—</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <button className="btn btn-ghost w-8 h-8 p-0" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
            ←
          </button>
          <span className="text-xs text-t3 tabular-nums">Página {page} de {pages}</span>
          <button className="btn btn-ghost w-8 h-8 p-0" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page === pages}>
            →
          </button>
        </div>
      )}

      {/* Create modal */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="Novo Relatório"
        size="sm"
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancelar</button>
            <button className="btn btn-primary" onClick={handleCreate} disabled={creating}>
              {creating ? 'Solicitando...' : 'Solicitar'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label">Tipo de Relatório</label>
            <select
              className="input"
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
            >
              {Object.entries(REPORT_TYPES).map(([key, val]) => (
                <option key={key} value={key}>{val.label}</option>
              ))}
            </select>
          </div>
          <div className="card p-3 bg-elevated">
            <p className="text-xs text-t3">
              O relatório será gerado em segundo plano. Você pode acompanhar o status na lista e baixar quando estiver pronto.
            </p>
          </div>
        </div>
      </Modal>
    </div>
  )
}
