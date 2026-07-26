import { useEffect, useState, useCallback } from 'react'
import {
  Plus, UserX, UserCheck, KeyRound, Search,
  Users,
} from 'lucide-react'
import { format } from 'date-fns'
import { usersService } from '@/services/users'
import { PageSpinner } from '@/components/ui/Spinner'
import { Badge } from '@/components/ui/Badge'
import { Modal } from '@/components/ui/Modal'
import { useAuthStore } from '@/store/authStore'
import toast from 'react-hot-toast'
import type { User, UserRole } from '@/types'

// ── constants ────────────────────────────────────────────────────────────────

const ROLE_LABEL: Record<string, string> = {
  admin:    'Admin',
  gestor:   'Gestor',
  operador: 'Operador',
  operator: 'Operador',
  viewer:   'Viewer',
}

// ── helpers ──────────────────────────────────────────────────────────────────

function Avatar({ name }: { name: string }) {
  return (
    <div
      className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-semibold shrink-0"
      style={{ background: 'var(--accent)' }}
    >
      {name.charAt(0).toUpperCase()}
    </div>
  )
}

// ── create modal ─────────────────────────────────────────────────────────────

interface CreateForm { email: string; password: string; full_name: string; role: UserRole }
const EMPTY_CREATE: CreateForm = { email: '', password: '', full_name: '', role: 'viewer' }

function CreateModal({
  open, onClose, onCreated,
}: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [form, setForm]     = useState<CreateForm>(EMPTY_CREATE)
  const [saving, setSaving] = useState(false)

  const reset = () => { setForm(EMPTY_CREATE); setSaving(false) }
  const close = () => { reset(); onClose() }

  const handle = async () => {
    if (!form.email || !form.password || !form.full_name) return
    setSaving(true)
    try {
      await usersService.create(form)
      toast.success('Usuário criado')
      reset()
      onCreated()
      onClose()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      toast.error(e.response?.data?.detail ?? 'Erro ao criar usuário')
    } finally { setSaving(false) }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Novo Usuário"
      size="sm"
      footer={
        <>
          <button className="btn btn-ghost" onClick={close}>Cancelar</button>
          <button
            className="btn btn-primary"
            onClick={handle}
            disabled={saving || !form.email || !form.password || !form.full_name}
          >
            {saving ? 'Criando...' : 'Criar'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <label className="label">Nome Completo *</label>
          <input
            className="input"
            placeholder="João Silva"
            value={form.full_name}
            onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Email *</label>
          <input
            type="email"
            className="input"
            placeholder="joao@empresa.com"
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Senha *</label>
          <input
            type="password"
            className="input"
            placeholder="Mínimo 8 caracteres"
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          />
        </div>
        <div>
          <label className="label">Papel</label>
          <select
            className="input"
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))}
          >
            <option value="viewer">Viewer — Apenas visualização</option>
            <option value="operator">Operador — Pode criar clips e eventos</option>
            <option value="admin">Admin — Acesso total</option>
          </select>
        </div>
      </div>
    </Modal>
  )
}

// ── reset password modal ──────────────────────────────────────────────────────

function ResetPasswordModal({
  user, onClose, onDone,
}: { user: User; onClose: () => void; onDone: () => void }) {
  const [pw, setPw]         = useState('')
  const [saving, setSaving] = useState(false)

  const handle = async () => {
    if (pw.length < 8) { toast.error('Senha deve ter no mínimo 8 caracteres'); return }
    setSaving(true)
    try {
      await usersService.update(user.id, { password: pw })
      toast.success(`Senha de ${user.full_name} redefinida`)
      onDone()
      onClose()
    } catch { toast.error('Erro ao redefinir senha') }
    finally { setSaving(false) }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Redefinir Senha — ${user.full_name}`}
      size="sm"
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button
            className="btn btn-primary"
            onClick={handle}
            disabled={saving || pw.length < 8}
          >
            {saving ? 'Salvando...' : 'Redefinir'}
          </button>
        </>
      }
    >
      <div>
        <label className="label">Nova Senha</label>
        <input
          type="password"
          className="input"
          placeholder="Mínimo 8 caracteres"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handle() }}
          autoFocus
        />
        <p className="text-xs text-t3 mt-1.5">
          O usuário precisará usar esta senha no próximo login.
        </p>
      </div>
    </Modal>
  )
}

// ── user row ─────────────────────────────────────────────────────────────────

function UserRow({
  user,
  currentUserId,
  onRoleChange,
  onToggleActive,
  onResetPassword,
  saving,
}: {
  user: User
  currentUserId: string
  onRoleChange: (u: User, role: UserRole) => void
  onToggleActive: (u: User) => void
  onResetPassword: (u: User) => void
  saving: boolean
}) {
  const isSelf = user.id === currentUserId

  return (
    <tr
      className="border-b transition"
      style={{
        borderColor: 'var(--border)',
        opacity: user.is_active ? 1 : 0.55,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--elevated)' }}
      onMouseLeave={(e) => { e.currentTarget.style.background = '' }}
    >
      {/* Nome */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2.5">
          <Avatar name={user.full_name} />
          <div className="min-w-0">
            <p className="text-sm font-medium text-t1 truncate">{user.full_name}</p>
            <p className="text-xs text-t3 truncate sm:hidden">{user.email}</p>
          </div>
        </div>
      </td>

      {/* Email — hidden on mobile */}
      <td className="px-4 py-3 text-t2 text-xs hidden sm:table-cell">{user.email}</td>

      {/* Papel — inline select */}
      <td className="px-4 py-3">
        <select
          className="text-xs rounded-lg px-2 py-1 font-medium border outline-none transition cursor-pointer disabled:cursor-default"
          style={{
            background: 'var(--elevated)',
            borderColor: 'var(--border)',
            color: 'var(--text-2)',
          }}
          value={user.role}
          disabled={saving || isSelf}
          title={isSelf ? 'Não é possível alterar o próprio papel' : undefined}
          onChange={(e) => onRoleChange(user, e.target.value as UserRole)}
        >
          <option value="viewer">Viewer</option>
          <option value="operator">Operador</option>
          <option value="admin">Admin</option>
        </select>
      </td>

      {/* Status — hidden on mobile */}
      <td className="px-4 py-3 hidden md:table-cell">
        <Badge variant={user.is_active ? 'success' : 'danger'} dot>
          {user.is_active ? 'Ativo' : 'Inativo'}
        </Badge>
      </td>

      {/* Criado em — hidden on mobile */}
      <td className="px-4 py-3 text-t3 text-xs hidden lg:table-cell">
        {format(new Date(user.created_at), 'dd/MM/yyyy')}
      </td>

      {/* Ações */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-1 justify-end">
          <button
            className="btn btn-ghost w-7 h-7 p-0 rounded-md text-t3 hover:text-t1"
            onClick={() => onResetPassword(user)}
            title="Redefinir senha"
            disabled={saving}
          >
            <KeyRound size={14} />
          </button>

          {user.is_active ? (
            <button
              className="btn btn-ghost w-7 h-7 p-0 rounded-md text-danger hover:text-danger"
              onClick={() => onToggleActive(user)}
              title="Desativar usuário"
              disabled={saving || isSelf}
            >
              <UserX size={14} />
            </button>
          ) : (
            <button
              className="btn btn-ghost w-7 h-7 p-0 rounded-md text-green-500 hover:text-green-400"
              onClick={() => onToggleActive(user)}
              title="Reativar usuário"
              disabled={saving}
            >
              <UserCheck size={14} />
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

// ── mobile card ───────────────────────────────────────────────────────────────

function UserCard({
  user,
  currentUserId,
  onRoleChange,
  onToggleActive,
  onResetPassword,
  saving,
}: {
  user: User
  currentUserId: string
  onRoleChange: (u: User, role: UserRole) => void
  onToggleActive: (u: User) => void
  onResetPassword: (u: User) => void
  saving: boolean
}) {
  const isSelf = user.id === currentUserId

  return (
    <div
      className="rounded-xl p-4 space-y-3 border"
      style={{
        background: 'var(--surface)',
        borderColor: 'var(--border)',
        opacity: user.is_active ? 1 : 0.55,
      }}
    >
      <div className="flex items-center gap-3">
        <Avatar name={user.full_name} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-t1 truncate">{user.full_name}</p>
          <p className="text-xs text-t3 truncate">{user.email}</p>
        </div>
        <Badge variant={user.is_active ? 'success' : 'danger'} dot>
          {user.is_active ? 'Ativo' : 'Inativo'}
        </Badge>
      </div>

      <div className="flex items-center justify-between gap-2">
        <select
          className="text-xs rounded-lg px-2 py-1.5 font-medium border outline-none flex-1 disabled:cursor-default"
          style={{
            background: 'var(--elevated)',
            borderColor: 'var(--border)',
            color: 'var(--text-2)',
          }}
          value={user.role}
          disabled={saving || isSelf}
          onChange={(e) => onRoleChange(user, e.target.value as UserRole)}
        >
          <option value="viewer">Viewer</option>
          <option value="operator">Operador</option>
          <option value="admin">Admin</option>
        </select>

        <div className="flex gap-1">
          <button
            className="btn btn-ghost w-8 h-8 p-0 rounded-lg text-t3"
            onClick={() => onResetPassword(user)}
            title="Redefinir senha"
            disabled={saving}
          >
            <KeyRound size={15} />
          </button>
          {user.is_active ? (
            <button
              className="btn btn-ghost w-8 h-8 p-0 rounded-lg text-danger"
              onClick={() => onToggleActive(user)}
              title="Desativar"
              disabled={saving || isSelf}
            >
              <UserX size={15} />
            </button>
          ) : (
            <button
              className="btn btn-ghost w-8 h-8 p-0 rounded-lg text-green-500"
              onClick={() => onToggleActive(user)}
              title="Reativar"
              disabled={saving}
            >
              <UserCheck size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── main page ────────────────────────────────────────────────────────────────

export function UsersPage() {
  const currentUser   = useAuthStore((s) => s.user)
  const [users, setUsers]             = useState<User[]>([])
  const [loading, setLoading]         = useState(true)
  const [saving, setSaving]           = useState(false)
  const [showCreate, setShowCreate]   = useState(false)
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [search, setSearch]           = useState('')
  const [showInactive, setShowInactive] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    usersService.list().then(setUsers).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const handleRoleChange = async (user: User, role: UserRole) => {
    setSaving(true)
    try {
      const updated = await usersService.update(user.id, { role })
      setUsers((prev) => prev.map((u) => u.id === user.id ? updated : u))
      toast.success(`Papel de ${user.full_name} alterado para ${ROLE_LABEL[role]}`)
    } catch { toast.error('Erro ao alterar papel') }
    finally { setSaving(false) }
  }

  const handleToggleActive = async (user: User) => {
    const action = user.is_active ? 'Desativar' : 'Reativar'
    if (!confirm(`${action} usuário "${user.full_name}"?`)) return
    setSaving(true)
    try {
      const updated = await usersService.update(user.id, { is_active: !user.is_active })
      setUsers((prev) => prev.map((u) => u.id === user.id ? updated : u))
      toast.success(`Usuário ${user.is_active ? 'desativado' : 'reativado'}`)
    } catch { toast.error('Erro ao atualizar usuário') }
    finally { setSaving(false) }
  }

  if (loading) return <PageSpinner />

  const filtered = users.filter((u) => {
    if (!showInactive && !u.is_active) return false
    if (!search) return true
    const q = search.toLowerCase()
    return u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
  })

  const activeCount   = users.filter((u) => u.is_active).length
  const inactiveCount = users.filter((u) => !u.is_active).length

  const rowProps = (user: User) => ({
    user,
    currentUserId: currentUser?.id ?? '',
    onRoleChange: handleRoleChange,
    onToggleActive: handleToggleActive,
    onResetPassword: setResetTarget,
    saving,
  })

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Top bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg flex-1 min-w-48"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <Search size={13} className="text-t3 shrink-0" />
          <input
            className="bg-transparent text-xs text-t1 outline-none placeholder:text-t3 w-full"
            placeholder="Buscar por nome ou email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Inactive toggle */}
        {inactiveCount > 0 && (
          <button
            onClick={() => setShowInactive((v) => !v)}
            className="text-xs px-3 py-2 rounded-lg font-medium transition-all"
            style={{
              background: showInactive ? 'rgba(239,68,68,0.1)' : 'var(--surface)',
              border: `1px solid ${showInactive ? 'rgba(239,68,68,0.3)' : 'var(--border)'}`,
              color: showInactive ? '#ef4444' : 'var(--text-3)',
            }}
          >
            {showInactive ? `Ocultar inativos (${inactiveCount})` : `Ver inativos (${inactiveCount})`}
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <p className="text-xs text-t3 hidden sm:block">
            {activeCount} ativo{activeCount !== 1 ? 's' : ''}
          </p>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={15} />
            <span className="hidden sm:inline">Novo Usuário</span>
            <span className="sm:hidden">Novo</span>
          </button>
        </div>
      </div>

      {/* Desktop table */}
      <div
        className="rounded-xl overflow-hidden hidden sm:block"
        style={{ border: '1px solid var(--border)' }}
      >
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-left border-b text-[10px] font-semibold uppercase tracking-wide text-t3"
              style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
            >
              <th className="px-4 py-3">Nome</th>
              <th className="px-4 py-3 hidden sm:table-cell">Email</th>
              <th className="px-4 py-3">Papel</th>
              <th className="px-4 py-3 hidden md:table-cell">Status</th>
              <th className="px-4 py-3 hidden lg:table-cell">Criado em</th>
              <th className="px-4 py-3 text-right">Ações</th>
            </tr>
          </thead>
          <tbody style={{ background: 'var(--surface)' }}>
            {filtered.map((user) => (
              <UserRow key={user.id} {...rowProps(user)} />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-14 text-center">
                  <Users size={32} className="mx-auto text-t3/20 mb-2" />
                  <p className="text-sm text-t3">Nenhum usuário encontrado</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="sm:hidden space-y-3">
        {filtered.map((user) => (
          <UserCard key={user.id} {...rowProps(user)} />
        ))}
        {filtered.length === 0 && (
          <div
            className="rounded-xl py-14 flex flex-col items-center justify-center"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
          >
            <Users size={32} className="text-t3/20 mb-2" />
            <p className="text-sm text-t3">Nenhum usuário encontrado</p>
          </div>
        )}
      </div>

      {/* Create modal */}
      <CreateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={load}
      />

      {/* Reset password modal */}
      {resetTarget && (
        <ResetPasswordModal
          user={resetTarget}
          onClose={() => setResetTarget(null)}
          onDone={load}
        />
      )}
    </div>
  )
}
