import { useEffect, useState, useCallback } from 'react'
import { Search, Download, Filter, X } from 'lucide-react'
import { format } from 'date-fns'
import { auditService, type AuditLogItem } from '@/services/audit'
import { PageSpinner } from '@/components/ui/Spinner'
import toast from 'react-hot-toast'

const PAGE_SIZE = 50

const RESULT_COLORS: Record<string, string> = {
  success: '#22c55e',
  error: '#ef4444',
  denied: '#f59e0b',
}

export function AuditPage() {
  const [logs, setLogs]         = useState<AuditLogItem[]>([])
  const [loading, setLoading]   = useState(true)
  const [page, setPage]         = useState(1)
  const [total, setTotal]       = useState(0)
  const [pendingFilters, setPendingFilters] = useState({ action: '', user_id: '', resource_type: '' })

  const load = useCallback((p: number, filters: { action?: string; user_id?: string; resource_type?: string }) => {
    setLoading(true)
    auditService.list({ page: p, page_size: PAGE_SIZE, ...filters })
      .then((r) => { setLogs(r.items); setTotal(r.total) })
      .catch(() => setLogs([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(page, pendingFilters) }, [page])

  const applyFilters = () => {
    const f = {
      action: pendingFilters.action || undefined,
      user_id: pendingFilters.user_id || undefined,
      resource_type: pendingFilters.resource_type || undefined,
    }
    setPage(1)
    load(1, f)
  }

  const clearFilters = () => {
    setPendingFilters({ action: '', user_id: '', resource_type: '' })
    setPage(1)
    load(1, {})
  }

  const exportCsv = useCallback(() => {
    const header = 'data_hora,usuario,acao,recurso,tipo_recurso,ip,resultado'
    const rows = logs.map((log) =>
      [
        format(new Date(log.occurred_at), 'dd/MM/yyyy HH:mm:ss'),
        log.user_email ?? 'Sistema',
        log.action,
        log.resource_name ?? log.resource_id ?? '—',
        log.resource_type ?? '—',
        log.ip_address ?? '—',
        log.result,
      ].map((x) => `"${String(x ?? '').replace(/"/g, '""')}"`).join(',')
    )
    const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv;charset=utf-8;' })
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `audit_${format(new Date(), 'yyyyMMdd_HHmmss')}.csv`,
    })
    a.click()
    URL.revokeObjectURL(a.href)
    toast.success('CSV exportado')
  }, [logs])

  const pages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Filters */}
      <div className="card p-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="min-w-36 flex-1">
            <label className="label">Ação</label>
            <div className="relative">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-t3" />
              <input
                className="input pl-8"
                placeholder="camera.created, user.login..."
                value={pendingFilters.action}
                onChange={(e) => setPendingFilters((f) => ({ ...f, action: e.target.value }))}
              />
            </div>
          </div>

          <div className="min-w-32 flex-1">
            <label className="label">Usuário</label>
            <input
              className="input"
              placeholder="Email ou ID"
              value={pendingFilters.user_id}
              onChange={(e) => setPendingFilters((f) => ({ ...f, user_id: e.target.value }))}
            />
          </div>

          <div className="min-w-32 flex-1">
            <label className="label">Tipo de Recurso</label>
            <input
              className="input"
              placeholder="camera, user, recording..."
              value={pendingFilters.resource_type}
              onChange={(e) => setPendingFilters((f) => ({ ...f, resource_type: e.target.value }))}
            />
          </div>

          <div className="flex gap-2">
            <button className="btn btn-primary gap-1.5" onClick={applyFilters}>
              <Filter size={14} /> Filtrar
            </button>
            {(pendingFilters.action || pendingFilters.user_id || pendingFilters.resource_type) && (
              <button className="btn btn-ghost" onClick={clearFilters} title="Limpar">
                <X size={15} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Total de registros', value: total.toLocaleString('pt-BR') },
          { label: 'Nesta página', value: logs.length.toString() },
          { label: 'Última atualização', value: format(new Date(), 'HH:mm:ss') },
        ].map(({ label, value }) => (
          <div key={label} className="card px-4 py-3">
            <p className="text-xs text-t3 mb-1">{label}</p>
            <p className="text-xl font-bold text-t1 tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between border-b text-xs text-t3" style={{ borderColor: 'var(--border)' }}>
          <span>{total.toLocaleString('pt-BR')} registros</span>
          <button className="btn btn-ghost text-xs gap-1.5" onClick={exportCsv} disabled={logs.length === 0}>
            <Download size={13} /> Exportar CSV
          </button>
        </div>

        {loading ? (
          <PageSpinner />
        ) : logs.length === 0 ? (
          <div className="py-16 text-center text-sm text-t3">Nenhum registro de auditoria encontrado</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[800px]">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: 'var(--border)' }}>
                  {['Data/Hora', 'Usuário', 'Ação', 'Recurso', 'IP', 'Resultado'].map((h) => (
                    <th key={h} className="px-3 py-2.5 text-xs font-medium text-t3 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => {
                  const color = RESULT_COLORS[log.result] ?? '#888'
                  return (
                    <tr key={log.id} className="border-b hover:bg-elevated transition" style={{ borderColor: 'var(--border)' }}>
                      <td className="px-3 py-2 text-xs text-t3 whitespace-nowrap tabular-nums">
                        {format(new Date(log.occurred_at), 'dd/MM/yy HH:mm:ss')}
                      </td>
                      <td className="px-3 py-2">
                        <p className="text-xs text-t1 truncate max-w-[160px]">
                          {log.user_email ?? 'Sistema'}
                        </p>
                        {log.user_role && (
                          <p className="text-xs text-t3">{log.user_role}</p>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <code className="text-xs bg-elevated px-1.5 py-0.5 rounded text-t2">
                          {log.action}
                        </code>
                      </td>
                      <td className="px-3 py-2 text-xs text-t2 max-w-[180px]">
                        <span className="truncate block">
                          {log.resource_name ?? log.resource_type ?? '—'}
                          {log.resource_id && (
                            <span className="text-t3 ml-1 font-mono text-xs">
                              {String(log.resource_id).slice(0, 8)}
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-t3">
                        {log.ip_address ?? '—'}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className="inline-flex items-center gap-1.5 text-xs font-medium px-1.5 py-0.5 rounded-full"
                          style={{ color, background: `${color}18` }}
                        >
                          {log.result}
                        </span>
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
          <button className="btn btn-ghost w-8 h-8 p-0" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>←</button>
          <span className="text-xs text-t3 tabular-nums">Página {page} de {pages}</span>
          <button className="btn btn-ghost w-8 h-8 p-0" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page === pages}>→</button>
        </div>
      )}
    </div>
  )
}
