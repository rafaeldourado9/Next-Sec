import { useEffect, useState } from 'react'
import { Plus, MoreVertical, Pause, Play, Trash2, UserCheck } from 'lucide-react'
import { adminService, type AdminTenant } from '@/services/admin'
import { PageSpinner } from '@/components/ui/Spinner'
import toast from 'react-hot-toast'
import { clsx } from 'clsx'

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500/20 text-green-400',
  suspended: 'bg-yellow-500/20 text-yellow-400',
}

interface CreateTenantModal {
  name: string; slug: string; gestor_email: string; gestor_password: string; cnpj: string
}

export function TenantsPage() {
  const [tenants, setTenants] = useState<AdminTenant[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<CreateTenantModal>({
    name: '', slug: '', gestor_email: '', gestor_password: '', cnpj: ''
  })
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const [impersonating, setImpersonating] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    adminService.listTenants().then(r => {
      setTenants(r.items)
      setTotal(r.total)
    }).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!form.name || !form.slug || !form.gestor_email || !form.gestor_password) {
      toast.error('Preencha todos os campos obrigatórios')
      return
    }
    try {
      await adminService.createTenant(form)
      toast.success('Tenant criado com sucesso')
      setShowCreate(false)
      setForm({ name: '', slug: '', gestor_email: '', gestor_password: '', cnpj: '' })
      load()
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? 'Erro ao criar tenant')
    }
  }

  const handleSuspend = async (id: string) => {
    try {
      await adminService.suspendTenant(id)
      toast.success('Tenant suspenso')
      load()
    } catch { toast.error('Erro ao suspender') }
    setOpenMenu(null)
  }

  const handleReactivate = async (id: string) => {
    try {
      await adminService.reactivateTenant(id)
      toast.success('Tenant reativado')
      load()
    } catch { toast.error('Erro ao reativar') }
    setOpenMenu(null)
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Tem certeza? Esta ação é irreversível.')) return
    try {
      await adminService.deleteTenant(id)
      toast.success('Tenant excluído')
      load()
    } catch { toast.error('Erro ao excluir') }
    setOpenMenu(null)
  }

  const handleImpersonate = async (id: string) => {
    setImpersonating(id)
    try {
      const result = await adminService.impersonateTenant(id)
      window.open(`/?impersonate=${result.access_token}&tenant=${result.tenant_name}`, '_blank')
      toast.success(`Impersonando ${result.tenant_name}`)
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? 'Erro ao impersonar')
    } finally {
      setImpersonating(null)
      setOpenMenu(null)
    }
  }

  if (loading) return <PageSpinner />

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Gestão de Tenants</h1>
          <p className="text-gray-400 text-sm">{total} tenants cadastrados</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium"
        >
          <Plus size={16} /> Novo Tenant
        </button>
      </div>

      {/* Table */}
      <div className="bg-gray-800 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-700/50 text-gray-300 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Nome</th>
              <th className="text-left px-4 py-3">CNPJ</th>
              <th className="text-left px-4 py-3">Câmeras</th>
              <th className="text-left px-4 py-3">Fatura Atual</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Ações</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {tenants.map(t => (
              <tr key={t.id} className="hover:bg-gray-700/30">
                <td className="px-4 py-3">
                  <div className="text-white font-medium">{t.name}</div>
                  <div className="text-gray-500 text-xs">{t.slug}</div>
                </td>
                <td className="px-4 py-3 text-gray-300 text-sm">{t.cnpj ?? '—'}</td>
                <td className="px-4 py-3 text-gray-300 text-sm">{t.cameras_count}</td>
                <td className="px-4 py-3 text-sm">
                  {t.latest_invoice ? (
                    <div>
                      <span className="text-white font-medium">
                        {new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(t.latest_invoice.total)}
                      </span>
                      <span className={clsx('ml-2 text-xs px-1.5 py-0.5 rounded', {
                        'bg-green-500/20 text-green-400': t.latest_invoice.status === 'paid',
                        'bg-yellow-500/20 text-yellow-400': t.latest_invoice.status === 'pending',
                        'bg-red-500/20 text-red-400': t.latest_invoice.status === 'overdue',
                      })}>
                        {t.latest_invoice.status}
                      </span>
                    </div>
                  ) : <span className="text-gray-500">—</span>}
                </td>
                <td className="px-4 py-3">
                  <span className={clsx('text-xs px-2 py-1 rounded', STATUS_COLORS[t.is_active ? 'active' : 'suspended'])}>
                    {t.is_active ? 'Ativo' : 'Suspenso'}
                  </span>
                </td>
                <td className="px-4 py-3 relative">
                  <button
                    onClick={() => setOpenMenu(openMenu === t.id ? null : t.id)}
                    className="text-gray-400 hover:text-white p-1 rounded"
                  >
                    <MoreVertical size={16} />
                  </button>
                  {openMenu === t.id && (
                    <div className="absolute right-0 top-10 z-10 bg-gray-700 border border-gray-600 rounded-lg shadow-lg py-1 min-w-40">
                      <button onClick={() => handleImpersonate(t.id)} disabled={!!impersonating}
                        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-200 hover:bg-gray-600">
                        <UserCheck size={14} /> Impersonar
                      </button>
                      {t.is_active ? (
                        <button onClick={() => handleSuspend(t.id)}
                          className="flex items-center gap-2 w-full px-3 py-2 text-sm text-yellow-400 hover:bg-gray-600">
                          <Pause size={14} /> Suspender
                        </button>
                      ) : (
                        <button onClick={() => handleReactivate(t.id)}
                          className="flex items-center gap-2 w-full px-3 py-2 text-sm text-green-400 hover:bg-gray-600">
                          <Play size={14} /> Reativar
                        </button>
                      )}
                      <button onClick={() => handleDelete(t.id)}
                        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-red-400 hover:bg-gray-600">
                        <Trash2 size={14} /> Excluir
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4" onClick={e => e.stopPropagation()}>
            <h2 className="text-xl font-bold text-white">Novo Tenant</h2>
            {[
              { label: 'Nome *', key: 'name', type: 'text' },
              { label: 'Slug *', key: 'slug', type: 'text' },
              { label: 'CNPJ', key: 'cnpj', type: 'text' },
              { label: 'Email do Gestor *', key: 'gestor_email', type: 'email' },
              { label: 'Senha do Gestor *', key: 'gestor_password', type: 'password' },
            ].map(f => (
              <div key={f.key}>
                <label className="block text-sm text-gray-400 mb-1">{f.label}</label>
                <input
                  type={f.type}
                  value={(form as any)[f.key]}
                  onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                  className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:border-blue-500 outline-none"
                />
              </div>
            ))}
            <div className="flex gap-3 pt-2">
              <button onClick={() => setShowCreate(false)} className="flex-1 bg-gray-700 text-gray-300 py-2 rounded-lg text-sm">Cancelar</button>
              <button onClick={handleCreate} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg text-sm font-medium">Criar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
