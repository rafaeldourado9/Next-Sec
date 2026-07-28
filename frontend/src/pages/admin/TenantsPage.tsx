import { useEffect, useState } from 'react'
import { Plus, MoreVertical, Pause, Play, Trash2, UserCheck, Download, Copy, Check } from 'lucide-react'
import { adminService, type AdminTenant, type OnboardClientResult } from '@/services/admin'
import { PageSpinner } from '@/components/ui/Spinner'
import toast from 'react-hot-toast'
import { clsx } from 'clsx'

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500/20 text-green-400',
  suspended: 'bg-yellow-500/20 text-yellow-400',
}

interface OnboardClientForm {
  name: string; slug: string; gestor_email: string; gestor_name: string; cnpj: string; max_cameras: string
}

const EMPTY_FORM: OnboardClientForm = {
  name: '', slug: '', gestor_email: '', gestor_name: '', cnpj: '', max_cameras: '',
}

// .env.edge — mesmos defaults de .env.edge.example (ver docs/DEPLOY_EDGE.md).
// VMS_API_URL vem do IP do hub WireGuard (wg_allowed_ips é o /32 do hub, não
// do agent — mesma convenção usada no pacote do Nível 2, ver services/agents.ts
// histórico).
const envEdge = (b: OnboardClientResult) => `VMS_API_URL=http://${b.agent.wg_allowed_ips.split('/')[0]}:8000
VMS_API_KEY=${b.agent.api_key}
ANALYTICS_TARGET=cpu
ANALYTICS_FPS=3
YOLO_IMGSZ=640
YOLO_CONF=0.30
YOLO_MODEL_PATH=/models/object.pt
FACE_RECOGNITION_MODEL_PATH=
LOG_LEVEL=INFO
`

const nextsecConf = (b: OnboardClientResult) => `[Interface]
PrivateKey = ${b.agent.wg_private_key}
Address = ${b.agent.wg_tunnel_ip}

[Peer]
PublicKey = ${b.agent.wg_public_key_hub}
Endpoint = ${b.agent.wg_endpoint}
AllowedIPs = ${b.agent.wg_allowed_ips}
PersistentKeepalive = 25
`

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      className="text-gray-400 hover:text-white p-1 rounded"
      title="Copiar"
    >
      {copied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
    </button>
  )
}

export function TenantsPage() {
  const [tenants, setTenants] = useState<AdminTenant[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<OnboardClientForm>(EMPTY_FORM)
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const [impersonating, setImpersonating] = useState<string | null>(null)
  const [createdBundle, setCreatedBundle] = useState<OnboardClientResult | null>(null)
  const [zipping, setZipping] = useState(false)

  const load = () => {
    setLoading(true)
    adminService.listTenants().then(r => {
      setTenants(r.items)
      setTotal(r.total)
    }).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!form.name || !form.slug || !form.gestor_email) {
      toast.error('Preencha nome, slug e email do gestor')
      return
    }
    setCreating(true)
    try {
      const bundle = await adminService.onboardClient({
        name: form.name,
        slug: form.slug,
        gestor_email: form.gestor_email,
        gestor_name: form.gestor_name || undefined,
        cnpj: form.cnpj || undefined,
        max_cameras: form.max_cameras ? Number(form.max_cameras) : undefined,
      })
      setCreatedBundle(bundle)
      setForm(EMPTY_FORM)
      load()
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? 'Erro ao criar cliente')
    } finally {
      setCreating(false)
    }
  }

  // Instalador (.bat/.ps1) e docker-compose.edge.yml são estáticos, iguais
  // pra qualquer cliente — só nextsec.conf e .env.edge são únicos. Monta o
  // .zip no navegador (mesma técnica usada pelo pacote do agent nativo,
  // Nível 2, antes de AgentsPage.tsx ser removida) — os segredos nunca saem
  // do cliente pra montar isso.
  const downloadZip = async (b: OnboardClientResult) => {
    setZipping(true)
    try {
      const JSZip = (await import('jszip')).default
      const zip = new JSZip()
      zip.file('nextsec.conf', nextsecConf(b))
      zip.file('.env.edge', envEdge(b))

      const staticFiles = [
        'docker-compose.edge.yml', 'INSTALAR.bat', 'install-docker.ps1',
        'UNINSTALAR.bat', 'uninstall-docker.ps1',
      ]
      await Promise.all(staticFiles.map(async (name) => {
        const res = await fetch(`/downloads/agent-docker/${name}`)
        if (!res.ok) throw new Error(`Falha ao baixar ${name}`)
        zip.file(name, await res.arrayBuffer())
      }))

      const blob = await zip.generateAsync({ type: 'blob' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `next-sec-edge-${b.tenant.slug}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      toast.error(e.message ?? 'Erro ao montar o pacote')
    } finally {
      setZipping(false)
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
          <Plus size={16} /> Novo Cliente (Nível 1 — Docker)
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

      {/* Create (onboarding) Modal */}
      {showCreate && !createdBundle && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-md space-y-4" onClick={e => e.stopPropagation()}>
            <div>
              <h2 className="text-xl font-bold text-white">Novo Cliente — Nível 1 (Docker dedicado)</h2>
              <p className="text-gray-400 text-xs mt-1">
                Cria o tenant, a licença já ativa e o agent com túnel WireGuard.
                Senha do gestor é gerada automaticamente (troca obrigatória no primeiro login).
              </p>
            </div>
            {[
              { label: 'Nome *', key: 'name', type: 'text' },
              { label: 'Slug *', key: 'slug', type: 'text' },
              { label: 'CNPJ', key: 'cnpj', type: 'text' },
              { label: 'Email do Gestor *', key: 'gestor_email', type: 'email' },
              { label: 'Nome do Gestor', key: 'gestor_name', type: 'text' },
              { label: 'Máx. câmeras (licença)', key: 'max_cameras', type: 'number' },
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
              <button onClick={handleCreate} disabled={creating}
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-2 rounded-lg text-sm font-medium disabled:opacity-50">
                {creating ? 'Criando...' : 'Criar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* One-time result — segredos exibidos só aqui, uma vez */}
      {createdBundle && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 w-full max-w-lg space-y-4">
            <div>
              <h2 className="text-xl font-bold text-white">Cliente criado — {createdBundle.tenant.name}</h2>
              <p className="text-yellow-400 text-xs mt-1">
                Guarde estas informações agora. Elas não são mostradas de novo depois de fechar esta janela.
              </p>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-400">Licença</label>
                <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                  <code className="text-sm text-white flex-1">{createdBundle.license_key}</code>
                  <CopyButton value={createdBundle.license_key} />
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-400">Login do gestor</label>
                <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                  <code className="text-sm text-white flex-1">{createdBundle.gestor_email}</code>
                  <CopyButton value={createdBundle.gestor_email} />
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-400">Senha padrão (troca obrigatória no 1º login)</label>
                <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                  <code className="text-sm text-white flex-1">{createdBundle.gestor_default_password}</code>
                  <CopyButton value={createdBundle.gestor_default_password} />
                </div>
              </div>
            </div>

            <button
              className="w-full flex items-center gap-2 justify-center bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium disabled:opacity-50"
              onClick={() => downloadZip(createdBundle)}
              disabled={zipping}
            >
              <Download size={16} /> {zipping ? 'Montando pacote...' : 'Baixar pacote completo (.zip)'}
            </button>
            <p className="text-xs text-gray-500">
              O .zip contém nextsec.conf, .env.edge e o instalador Windows
              (INSTALAR.bat) — ver docs/DEPLOY_EDGE.md.
            </p>

            <button
              onClick={() => { setCreatedBundle(null); setShowCreate(false) }}
              className="w-full bg-gray-700 text-gray-300 py-2 rounded-lg text-sm"
            >
              Fechar
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
