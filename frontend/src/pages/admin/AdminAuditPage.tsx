import { useEffect, useState } from 'react'
import { Download, Search } from 'lucide-react'
import { api } from '@/services/api'
import { PageSpinner } from '@/components/ui/Spinner'
import toast from 'react-hot-toast'

interface AuditLog {
  id: string
  tenant_id: string
  user_id: string | null
  user_email: string | null
  user_role: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  ip_address: string | null
  occurred_at: string | null
  payload: Record<string, any> | null
}

export function AdminAuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ action: '', tenant_id: '' })
  const [selected, setSelected] = useState<AuditLog | null>(null)

  const load = () => {
    setLoading(true)
    api.get('/audit/logs', { params: { ...filters, limit: 50 } })
      .then(r => {
        const data = r.data
        setLogs(Array.isArray(data) ? data : data.items ?? [])
        setTotal(data.total ?? (Array.isArray(data) ? data.length : 0))
      })
      .catch(() => toast.error('Erro ao carregar logs'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleExport = async () => {
    try {
      const { data } = await api.get('/audit/logs/export.csv', { responseType: 'blob', params: filters })
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a')
      a.href = url; a.download = 'audit_global.csv'; a.click()
      URL.revokeObjectURL(url)
    } catch { toast.error('Erro ao exportar') }
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Auditoria Global</h1>
          <p className="text-gray-400 text-sm">{total} registros</p>
        </div>
        <button onClick={handleExport} className="flex items-center gap-2 text-gray-400 hover:text-white border border-gray-600 px-3 py-1.5 rounded-lg text-sm">
          <Download size={14} /> Exportar CSV
        </button>
      </div>

      <div className="flex gap-3">
        <input
          value={filters.action} onChange={e => setFilters(f => ({ ...f, action: e.target.value }))}
          placeholder="Filtrar por ação..."
          className="flex-1 bg-gray-800 text-white border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none"
        />
        <input
          value={filters.tenant_id} onChange={e => setFilters(f => ({ ...f, tenant_id: e.target.value }))}
          placeholder="Tenant ID..."
          className="w-64 bg-gray-800 text-white border border-gray-600 rounded-lg px-3 py-2 text-sm outline-none"
        />
        <button onClick={load} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm">
          <Search size={16} />
        </button>
      </div>

      {loading ? <PageSpinner /> : (
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-700/50 text-gray-300 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3">Timestamp</th>
                <th className="text-left px-4 py-3">Ação</th>
                <th className="text-left px-4 py-3">Usuário</th>
                <th className="text-left px-4 py-3">Recurso</th>
                <th className="text-left px-4 py-3">IP</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {logs.map(log => (
                <tr key={log.id} className="hover:bg-gray-700/20">
                  <td className="px-4 py-2 text-gray-400">
                    {log.occurred_at ? new Date(log.occurred_at).toLocaleString('pt-BR') : '—'}
                  </td>
                  <td className="px-4 py-2">
                    <span className="font-mono text-blue-300 text-xs">{log.action}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-300">
                    {log.user_email ?? log.user_id?.slice(0, 8) ?? '—'}
                    {log.user_role && <span className="ml-1 text-xs text-gray-500">({log.user_role})</span>}
                  </td>
                  <td className="px-4 py-2 text-gray-400">
                    {log.resource_type && <span>{log.resource_type}</span>}
                    {log.resource_id && <span className="ml-1 text-gray-600 text-xs">{log.resource_id.slice(0, 8)}</span>}
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{log.ip_address ?? '—'}</td>
                  <td className="px-4 py-2">
                    {log.payload && Object.keys(log.payload).length > 0 && (
                      <button onClick={() => setSelected(log)} className="text-xs text-blue-400 hover:text-blue-300">detalhes</button>
                    )}
                  </td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr><td colSpan={6} className="text-center text-gray-500 py-8">Nenhum log encontrado.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setSelected(null)}>
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-white mb-3">{selected.action}</h3>
            <pre className="bg-gray-900 rounded p-3 text-xs text-green-400 overflow-auto max-h-64">
              {JSON.stringify(selected.payload, null, 2)}
            </pre>
            <button onClick={() => setSelected(null)} className="mt-3 w-full bg-gray-700 text-gray-300 py-2 rounded-lg text-sm">Fechar</button>
          </div>
        </div>
      )}
    </div>
  )
}
