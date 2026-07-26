import { useEffect, useState } from 'react'
import { Plus, Trash2, ToggleLeft, ToggleRight, Bell, AlertCircle } from 'lucide-react'
import { format } from 'date-fns'
import { notificationsService } from '@/services/notifications'
import { PageSpinner } from '@/components/ui/Spinner'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { usePermission } from '@/hooks/usePermission'
import toast from 'react-hot-toast'
import type { NotificationRule, NotificationLog } from '@/types'

interface RuleForm {
  name: string
  event_type_pattern: string
  destination_url: string
  webhook_secret: string
}

const DEFAULT_FORM: RuleForm = {
  name: '',
  event_type_pattern: '*',
  destination_url: '',
  webhook_secret: '',
}

export function NotificationsPage() {
  const { isAdmin } = usePermission()
  const [rules, setRules]         = useState<NotificationRule[]>([])
  const [logs, setLogs]           = useState<NotificationLog[]>([])
  const [loading, setLoading]     = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating]   = useState(false)
  const [form, setForm]           = useState<RuleForm>(DEFAULT_FORM)

  const load = () => {
    Promise.all([
      notificationsService.listRules(),
      notificationsService.listLogs({ page_size: 20 }).catch(() => ({ items: [], total: 0, page: 1, page_size: 20, pages: 1 })),
    ]).then(([r, l]) => {
      setRules(r)
      setLogs(l.items ?? [])
    }).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!form.name || !form.destination_url) return
    setCreating(true)
    try {
      await notificationsService.createRule({
        name:               form.name,
        event_type_pattern: form.event_type_pattern,
        destination_url:    form.destination_url,
        webhook_secret:     form.webhook_secret || undefined,
      })
      toast.success('Regra criada')
      setShowCreate(false)
      setForm(DEFAULT_FORM)
      load()
    } catch { toast.error('Erro ao criar regra') } finally {
      setCreating(false)
    }
  }

  const handleToggle = async (rule: NotificationRule) => {
    try {
      await notificationsService.updateRule(rule.id, { is_active: !rule.is_active })
      setRules((prev) => prev.map((r) => r.id === rule.id ? { ...r, is_active: !r.is_active } : r))
    } catch { toast.error('Erro ao atualizar regra') }
  }

  const handleDelete = async (rule: NotificationRule) => {
    if (!confirm(`Remover regra "${rule.name}"?`)) return
    try {
      await notificationsService.deleteRule(rule.id)
      toast.success('Regra removida')
      load()
    } catch { toast.error('Erro ao remover regra') }
  }

  if (loading) return <PageSpinner />

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Rules */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-sm font-semibold text-t1">Regras de Notificação</p>
            <p className="text-xs text-t3 mt-0.5">Webhooks acionados por eventos do sistema</p>
          </div>
          {isAdmin && (
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              <Plus size={16} />Nova Regra
            </button>
          )}
        </div>

        <div className="space-y-3">
          {rules.map((rule) => (
            <div key={rule.id} className="card p-4 flex items-start gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <p className="text-sm font-semibold text-t1">{rule.name}</p>
                  <Badge variant={rule.is_active ? 'success' : 'default'} dot>
                    {rule.is_active ? 'Ativa' : 'Inativa'}
                  </Badge>
                </div>
                <p className="text-xs text-t3">Padrão: <code className="text-t2">{rule.event_type_pattern}</code></p>
                <p className="text-xs text-t3 truncate mt-0.5">URL: {rule.destination_url}</p>
              </div>
              {isAdmin && (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    className="btn btn-ghost w-8 h-8 p-0"
                    onClick={() => handleToggle(rule)}
                    title={rule.is_active ? 'Desativar' : 'Ativar'}
                  >
                    {rule.is_active
                      ? <ToggleRight size={18} className="text-green-500" />
                      : <ToggleLeft size={18} className="text-t3" />}
                  </button>
                  <button
                    className="btn btn-ghost w-8 h-8 p-0 text-danger"
                    onClick={() => handleDelete(rule)}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              )}
            </div>
          ))}
          {rules.length === 0 && (
            <div className="card p-12 text-center">
              <Bell size={28} className="text-t3 mx-auto mb-3" />
              <p className="text-t3 text-sm">Nenhuma regra configurada</p>
            </div>
          )}
        </div>
      </div>

      {/* Logs */}
      <div>
        <p className="text-sm font-semibold text-t1 mb-3">Logs Recentes</p>
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left" style={{ borderColor: 'var(--border)' }}>
                {['Regra', 'Status', 'Tentativas', 'Enviado em'].map((h) => (
                  <th key={h} className="px-4 py-3 text-xs font-medium text-t3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id} className="border-b hover:bg-elevated transition" style={{ borderColor: 'var(--border)' }}>
                  <td className="px-4 py-3 text-t2 text-xs font-mono">
                    {rules.find((r) => r.id === log.rule_id)?.name ?? log.rule_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3">
                    {log.status_code ? (
                      <Badge variant={log.status_code < 300 ? 'success' : 'danger'}>
                        {log.status_code}
                      </Badge>
                    ) : (
                      <Badge variant="warning"><AlertCircle size={11} />Pendente</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-t2 text-xs">{log.attempt_count}</td>
                  <td className="px-4 py-3 text-t3 text-xs">
                    {log.sent_at ? format(new Date(log.sent_at), 'dd/MM HH:mm:ss') : '—'}
                  </td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-12 text-center text-t3 text-sm">
                    Nenhum log disponível
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create modal */}
      <Modal
        open={showCreate}
        onClose={() => { setShowCreate(false); setForm(DEFAULT_FORM) }}
        title="Nova Regra de Notificação"
        size="md"
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancelar</button>
            <button
              className="btn btn-primary"
              onClick={handleCreate}
              disabled={creating || !form.name || !form.destination_url}
            >
              {creating ? 'Criando...' : 'Criar Regra'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label">Nome *</label>
            <input
              className="input"
              placeholder="Ex: Alerta ALPR"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div>
            <label className="label">Padrão de Evento</label>
            <input
              className="input font-mono"
              placeholder="alpr, intrusion, * (todos)"
              value={form.event_type_pattern}
              onChange={(e) => setForm((f) => ({ ...f, event_type_pattern: e.target.value }))}
            />
            <p className="text-xs text-t3 mt-1">Use <code>*</code> para todos os eventos, ou um tipo específico como <code>alpr</code></p>
          </div>
          <div>
            <label className="label">URL de Destino *</label>
            <input
              className="input"
              type="url"
              placeholder="https://exemplo.com/webhook"
              value={form.destination_url}
              onChange={(e) => setForm((f) => ({ ...f, destination_url: e.target.value }))}
            />
          </div>
          <div>
            <label className="label">Segredo HMAC (opcional)</label>
            <input
              className="input font-mono"
              placeholder="Chave para verificação de autenticidade"
              value={form.webhook_secret}
              onChange={(e) => setForm((f) => ({ ...f, webhook_secret: e.target.value }))}
            />
            <p className="text-xs text-t3 mt-1">
              Se fornecido, o VMS enviará o header <code>X-VMS-Signature</code> com HMAC-SHA256
            </p>
          </div>
        </div>
      </Modal>
    </div>
  )
}
