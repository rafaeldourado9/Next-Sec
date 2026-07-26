import { useEffect, useState } from 'react'
import { Plus, Trash2, Phone, Power, PowerOff } from 'lucide-react'
import { format } from 'date-fns'
import { contactsService, type Contact } from '@/services/contacts'
import { camerasService } from '@/services/cameras'
import type { Camera } from '@/types'
import { PageSpinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import { usePermission } from '@/hooks/usePermission'
import toast from 'react-hot-toast'

const E164_RE = /^\+[1-9]\d{1,14}$/

export function ContactsPage() {
  const { isAdmin } = usePermission()
  const [contacts, setContacts] = useState<Contact[]>([])
  const [cameras, setCameras]   = useState<Camera[]>([])
  const [loading, setLoading]   = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: '', phone_number: '', camera_id: '' })

  const load = () => {
    contactsService.list()
      .then(setContacts)
      .catch(() => setContacts([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    camerasService.list().then(setCameras).catch(() => setCameras([]))
  }, [])

  const cameraName = (id: string | null) => {
    if (!id) return 'Todas as câmeras'
    return cameras.find((c) => c.id === id)?.name ?? id
  }

  const phoneValid = E164_RE.test(form.phone_number.trim())

  const handleCreate = async () => {
    if (!form.name.trim() || !phoneValid) return
    setCreating(true)
    try {
      await contactsService.create({
        name: form.name.trim(),
        phone_number: form.phone_number.trim(),
        camera_id: form.camera_id || null,
      })
      toast.success('Contato cadastrado')
      setShowCreate(false)
      setForm({ name: '', phone_number: '', camera_id: '' })
      load()
    } catch {
      toast.error('Erro ao cadastrar contato')
    } finally {
      setCreating(false)
    }
  }

  const handleToggle = async (contact: Contact) => {
    try {
      await contactsService.update(contact.id, { is_active: !contact.is_active })
      toast.success(contact.is_active ? 'Contato desativado' : 'Contato ativado')
      load()
    } catch {
      toast.error('Erro ao atualizar contato')
    }
  }

  const handleDelete = async (contact: Contact) => {
    if (!confirm(`Remover contato "${contact.name}"?`)) return
    try {
      await contactsService.del(contact.id)
      toast.success('Contato removido')
      load()
    } catch {
      toast.error('Erro ao remover contato')
    }
  }

  if (loading) return <PageSpinner />

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-t1">Contatos</p>
          <p className="text-xs text-t3 mt-0.5">
            Telefones que recebem alerta via WhatsApp quando um evento é detectado
          </p>
        </div>
        <button className="btn btn-primary gap-2" onClick={() => setShowCreate(true)}>
          <Plus size={16} />Novo Contato
        </button>
      </div>

      {contacts.length === 0 ? (
        <div className="card p-12 text-center">
          <Phone size={32} className="text-t3 mx-auto mb-3 opacity-30" />
          <p className="text-t3 text-sm">Nenhum contato cadastrado</p>
          <button className="btn btn-ghost text-xs mt-3" onClick={() => setShowCreate(true)}>
            Cadastrar primeiro contato
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {contacts.map((contact) => (
            <div key={contact.id} className="card p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Phone size={18} className="text-t2" />
                  <div>
                    <p className="text-sm font-semibold text-t1">{contact.name}</p>
                    <p className="text-xs text-t3">{contact.phone_number}</p>
                  </div>
                </div>
                <span
                  className="inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded-full"
                  style={
                    contact.is_active
                      ? { color: '#22c55e', background: '#22c55e18' }
                      : { color: '#71717a', background: '#71717a18' }
                  }
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: contact.is_active ? '#22c55e' : '#71717a' }}
                  />
                  {contact.is_active ? 'Ativo' : 'Inativo'}
                </span>
              </div>

              <p className="text-xs text-t3">
                Alertas de: <span className="text-t2">{cameraName(contact.camera_id)}</span>
              </p>

              <div className="flex items-center justify-between pt-2 border-t text-xs text-t3" style={{ borderColor: 'var(--border)' }}>
                <span>Cadastrado em {format(new Date(contact.created_at), 'dd/MM/yyyy')}</span>
                {isAdmin && (
                  <div className="flex items-center gap-1">
                    <button className="btn btn-ghost w-7 h-7 p-0" onClick={() => handleToggle(contact)} title="Ativar/desativar">
                      {contact.is_active ? <PowerOff size={14} /> : <Power size={14} />}
                    </button>
                    <button className="btn btn-ghost w-7 h-7 p-0 text-danger" onClick={() => handleDelete(contact)} title="Remover">
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={showCreate}
        onClose={() => { setShowCreate(false); setForm({ name: '', phone_number: '', camera_id: '' }) }}
        title="Novo Contato"
        size="sm"
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancelar</button>
            <button
              className="btn btn-primary"
              onClick={handleCreate}
              disabled={creating || !form.name.trim() || !phoneValid}
            >
              {creating ? 'Cadastrando...' : 'Cadastrar'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="label">Nome *</label>
            <input
              className="input"
              placeholder="Ex: João (síndico)"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div>
            <label className="label">Telefone (WhatsApp) *</label>
            <input
              className="input"
              placeholder="+5511999999999"
              value={form.phone_number}
              onChange={(e) => setForm((f) => ({ ...f, phone_number: e.target.value }))}
            />
            {form.phone_number.length > 0 && !phoneValid && (
              <p className="text-xs text-danger mt-1">
                Formato inválido — use +código do país e DDD, ex: +5511999999999
              </p>
            )}
          </div>
          <div>
            <label className="label">Câmera</label>
            <select
              className="input"
              value={form.camera_id}
              onChange={(e) => setForm((f) => ({ ...f, camera_id: e.target.value }))}
            >
              <option value="">Todas as câmeras</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
        </div>
      </Modal>
    </div>
  )
}
