import { useEffect, useState } from 'react'
import { Plus, Trash2, Cpu, MemoryStick, Activity, CircleDot, Power, PowerOff, Download } from 'lucide-react'
import { format } from 'date-fns'
import { agentsService, type Agent, type CreateAgentResult } from '@/services/agents'
import { PageSpinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import { usePermission } from '@/hooks/usePermission'
import toast from 'react-hot-toast'

const STATUS_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  online:  { color: '#22c55e', bg: '#22c55e18', label: 'Online' },
  offline: { color: '#ef4444', bg: '#ef444418', label: 'Offline' },
  pending: { color: '#f59e0b', bg: '#f59e0b18', label: 'Pendente' },
}

export function AgentsPage() {
  const { isAdmin } = usePermission()
  const [agents, setAgents]       = useState<Agent[]>([])
  const [loading, setLoading]     = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName]     = useState('')
  const [creating, setCreating]   = useState(false)
  // Bundle do túnel WireGuard — só existe entre a criação e o fechamento do
  // modal: a chave privada não é re-consultável depois disso (mesma garantia
  // da API key), então precisa ser mostrada/baixada agora ou nunca mais.
  const [createdBundle, setCreatedBundle] = useState<CreateAgentResult | null>(null)
  const [zipping, setZipping] = useState(false)

  const load = () => {
    agentsService.list()
      .then(setAgents)
      .catch(() => setAgents([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const result = await agentsService.create(newName.trim())
      setCreatedBundle(result)
      load()
    } catch {
      toast.error('Erro ao criar agent')
    } finally {
      setCreating(false)
    }
  }

  const closeCreateModal = () => {
    setShowCreate(false)
    setNewName('')
    setCreatedBundle(null)
  }

  const downloadText = (filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const wg0Conf = (b: CreateAgentResult) => `[Interface]
PrivateKey = ${b.wg_private_key}
Address = ${b.wg_tunnel_ip}

[Peer]
PublicKey = ${b.wg_public_key_hub}
Endpoint = ${b.wg_endpoint}
AllowedIPs = ${b.wg_allowed_ips}
PersistentKeepalive = 25
`

  const configEnv = (b: CreateAgentResult) => `AGENT_ID=${b.id}
AGENT_API_KEY=${b.api_key}
VMS_API_URL=http://${b.wg_allowed_ips.split('/')[0]}:8000
MEDIAMTX_RTMP_URL=rtmp://${b.wg_allowed_ips.split('/')[0]}:1935
`

  // Instalador (exe/scripts) é estático e igual pra qualquer agent — só os
  // 2 arquivos de texto acima são únicos por agent. Busca os estáticos do
  // próprio nginx (mesma origem) e monta um .zip único no navegador — a
  // chave privada nunca sai do cliente pra montar isso (nenhuma chamada
  // nova ao servidor com o segredo).
  const downloadZip = async (b: CreateAgentResult) => {
    setZipping(true)
    try {
      const JSZip = (await import('jszip')).default
      const zip = new JSZip()
      zip.file('nextsec.conf', wg0Conf(b))
      zip.file('config.env', configEnv(b))

      const staticFiles = ['next-sec-agent.exe', 'nssm.exe', 'install.ps1', 'uninstall.ps1', 'INSTALAR.bat', 'UNINSTALAR.bat']
      await Promise.all(staticFiles.map(async (name) => {
        const res = await fetch(`/downloads/agent-windows/${name}`)
        if (!res.ok) throw new Error(`Falha ao baixar ${name}`)
        zip.file(name, await res.arrayBuffer())
      }))

      const blob = await zip.generateAsync({ type: 'blob' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `next-sec-agent-${b.name}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Erro ao montar o pacote — baixe os arquivos separadamente abaixo')
    } finally {
      setZipping(false)
    }
  }

  const handleDelete = async (agent: Agent) => {
    if (!confirm(`Remover agent "${agent.name}"?`)) return
    try {
      await agentsService.delete(agent.id)
      toast.success('Agent removido')
      load()
    } catch {
      toast.error('Erro ao remover agent')
    }
  }

  const handleToggle = async (agent: Agent) => {
    try {
      await agentsService.update(agent.id, { is_active: agent.status !== 'offline' })
      toast.success(`Agent ${agent.status === 'offline' ? 'ativado' : 'desativado'}`)
      load()
    } catch {
      toast.error('Erro ao atualizar agent')
    }
  }

  if (loading) return <PageSpinner />

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-t1">Edge Agents</p>
          <p className="text-xs text-t3 mt-0.5">Agents de captura RTSP → MediaMTX</p>
        </div>
        {isAdmin && (
          <button className="btn btn-primary gap-2" onClick={() => setShowCreate(true)}>
            <Plus size={16} />Novo Agent
          </button>
        )}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Total', value: agents.length.toString(), icon: CircleDot, color: '#3b82f6' },
          { label: 'Online', value: agents.filter(a => a.status === 'online').length.toString(), icon: Power, color: '#22c55e' },
          { label: 'Offline', value: agents.filter(a => a.status === 'offline').length.toString(), icon: PowerOff, color: '#ef4444' },
          { label: 'Streams', value: agents.reduce((s, a) => s + (a.streams_running || 0), 0).toString(), icon: Activity, color: '#8b5cf6' },
        ].map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="card px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <Icon size={14} style={{ color }} />
              <p className="text-xs text-t3">{label}</p>
            </div>
            <p className="text-xl font-bold text-t1 tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      {/* Agents list */}
      {agents.length === 0 ? (
        <div className="card p-12 text-center">
          <Cpu size={32} className="text-t3 mx-auto mb-3 opacity-30" />
          <p className="text-t3 text-sm">Nenhum agent registrado</p>
          {isAdmin && (
            <button className="btn btn-ghost text-xs mt-3" onClick={() => setShowCreate(true)}>
              Criar primeiro agent
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {agents.map(agent => {
            const statusCfg = STATUS_CONFIG[agent.status] ?? STATUS_CONFIG.pending
            return (
              <div key={agent.id} className="card p-4 space-y-3">
                {/* Header */}
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <Cpu size={18} className="text-t2" />
                    <div>
                      <p className="text-sm font-semibold text-t1">{agent.name}</p>
                      {agent.hostname && <p className="text-xs text-t3">{agent.hostname}</p>}
                    </div>
                  </div>
                  <span
                    className="inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded-full"
                    style={{ color: statusCfg.color, background: statusCfg.bg }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: statusCfg.color }} />
                    {statusCfg.label}
                  </span>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div className="flex items-center gap-1.5 text-t3">
                    <Activity size={12} />
                    <span>{agent.streams_running} streams</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-t3">
                    <Cpu size={12} />
                    <span>{agent.cpu_usage != null ? `${agent.cpu_usage}%` : '—'}</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-t3">
                    <MemoryStick size={12} />
                    <span>{agent.ram_usage != null ? `${agent.ram_usage}%` : '—'}</span>
                  </div>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between pt-2 border-t text-xs text-t3" style={{ borderColor: 'var(--border)' }}>
                  <span>
                    {agent.last_heartbeat_at
                      ? `Último heartbeat: ${format(new Date(agent.last_heartbeat_at), 'HH:mm:ss')}`
                      : 'Sem heartbeat'}
                  </span>
                  {isAdmin && (
                    <div className="flex items-center gap-1">
                      <button className="btn btn-ghost w-7 h-7 p-0" onClick={() => handleToggle(agent)} title="Toggle">
                        {agent.status === 'offline' ? <Power size={14} /> : <PowerOff size={14} />}
                      </button>
                      <button className="btn btn-ghost w-7 h-7 p-0 text-danger" onClick={() => handleDelete(agent)} title="Remover">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create modal */}
      <Modal
        open={showCreate}
        onClose={closeCreateModal}
        title={createdBundle ? 'Túnel do agent criado' : 'Novo Edge Agent'}
        size={createdBundle ? 'md' : 'sm'}
        footer={
          createdBundle ? (
            <button className="btn btn-primary" onClick={closeCreateModal}>Fechar</button>
          ) : (
            <>
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancelar</button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={creating || !newName.trim()}>
                {creating ? 'Criando...' : 'Criar Agent'}
              </button>
            </>
          )
        }
      >
        {createdBundle ? (
          <div className="space-y-4">
            <div className="card p-3 bg-red-500/10 border border-red-500/30 text-xs text-red-300">
              <p><strong>Guarde agora.</strong> A chave privada do túnel e a API key não são mostradas de novo depois de fechar esta janela.</p>
            </div>
            <div>
              <button
                className="btn btn-primary gap-2 justify-center w-full"
                onClick={() => downloadZip(createdBundle)}
                disabled={zipping}
              >
                <Download size={16} /> {zipping ? 'Montando pacote...' : 'Baixar pacote completo (.zip)'}
              </button>
              <p className="text-xs text-t3 mt-2">
                Extraia na máquina do cliente e dê duplo-clique em <strong>INSTALAR.bat</strong> — ele pede permissão de administrador (UAC) sozinho e instala o túnel + o agent como serviços do Windows.
              </p>
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer text-t3 hover:text-t2">Baixar arquivos separados (avançado)</summary>
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <button className="btn btn-ghost gap-2 justify-center border border-border" onClick={() => downloadText('nextsec.conf', wg0Conf(createdBundle))}>
                    <Download size={14} /> nextsec.conf
                  </button>
                  <button className="btn btn-ghost gap-2 justify-center border border-border" onClick={() => downloadText('config.env', configEnv(createdBundle))}>
                    <Download size={14} /> config.env
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <a className="btn btn-ghost gap-2 justify-center border border-border" href="/downloads/agent-windows/next-sec-agent.exe" download>
                    <Download size={14} /> agent.exe
                  </a>
                  <a className="btn btn-ghost gap-2 justify-center border border-border" href="/downloads/agent-windows/nssm.exe" download>
                    <Download size={14} /> nssm.exe
                  </a>
                  <a className="btn btn-ghost gap-2 justify-center border border-border" href="/downloads/agent-windows/install.ps1" download>
                    <Download size={14} /> install.ps1
                  </a>
                  <a className="btn btn-ghost gap-2 justify-center border border-border" href="/downloads/agent-windows/uninstall.ps1" download>
                    <Download size={14} /> uninstall.ps1
                  </a>
                </div>
              </div>
            </details>
            <div>
              <label className="label">nextsec.conf (WireGuard)</label>
              <pre className="card p-3 bg-elevated text-[11px] overflow-x-auto whitespace-pre-wrap break-all">{wg0Conf(createdBundle)}</pre>
            </div>
            <div>
              <label className="label">config.env (edge_agent)</label>
              <pre className="card p-3 bg-elevated text-[11px] overflow-x-auto whitespace-pre-wrap break-all">{configEnv(createdBundle)}</pre>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="label">Nome do Agent *</label>
              <input
                className="input"
                placeholder="edge-agent-01"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
            <div className="card p-3 bg-elevated text-xs text-t3">
              <p>Cria o agent, a API key e um túnel WireGuard pra ele — o cliente não precisa de IP fixo pra se conectar de volta ao sistema.</p>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
