import { useState } from 'react'
import { KeyRound, ShieldAlert, AlertCircle, Loader2 } from 'lucide-react'
import { authService } from '@/services/auth'
import { useAuthStore } from '@/store/authStore'

function ChangePasswordScreen() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { tokens, setTokens, logout } = useAuthStore()

  const handleSubmit = async () => {
    if (newPassword.length < 8) {
      setError('A nova senha precisa ter pelo menos 8 caracteres.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('As senhas não coincidem.')
      return
    }
    setLoading(true)
    setError('')
    try {
      await authService.changePassword(currentPassword, newPassword)
      // Zera o flag localmente — não precisa de novo login, o token de
      // acesso continua válido (só a senha mudou).
      if (tokens) setTokens({ ...tokens, must_change_password: false })
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Senha atual incorreta.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center"
      style={{ background: 'var(--bg)', fontFamily: 'inherit' }}
    >
      <div
        className="w-full max-w-md mx-4 rounded-2xl overflow-hidden"
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          boxShadow: '0 32px 80px rgba(0,0,0,0.6)',
        }}
      >
        <div
          className="px-8 py-7 text-center"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-4"
            style={{ background: 'rgba(234,179,8,0.12)', border: '1px solid rgba(234,179,8,0.2)' }}
          >
            <ShieldAlert size={22} style={{ color: '#eab308' }} />
          </div>
          <h1 className="text-base font-semibold text-t1">Defina sua senha</h1>
          <p className="text-xs text-t3 mt-1">
            Esta conta ainda usa a senha padrão gerada no cadastro — troque-a antes de continuar.
          </p>
        </div>

        <div className="px-8 py-6 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-t2 uppercase tracking-wide">Senha atual</label>
            <input
              type="password"
              value={currentPassword}
              className="w-full px-3 py-2.5 rounded-lg text-sm text-t1 outline-none focus:ring-1"
              style={{ background: 'var(--elevated)', border: '1px solid var(--border)', '--tw-ring-color': '#eab308' } as React.CSSProperties}
              onChange={(e) => { setCurrentPassword(e.target.value); setError('') }}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-t2 uppercase tracking-wide">Nova senha</label>
            <input
              type="password"
              value={newPassword}
              className="w-full px-3 py-2.5 rounded-lg text-sm text-t1 outline-none focus:ring-1"
              style={{ background: 'var(--elevated)', border: '1px solid var(--border)', '--tw-ring-color': '#eab308' } as React.CSSProperties}
              onChange={(e) => { setNewPassword(e.target.value); setError('') }}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-t2 uppercase tracking-wide">Confirmar nova senha</label>
            <input
              type="password"
              value={confirmPassword}
              className="w-full px-3 py-2.5 rounded-lg text-sm text-t1 outline-none focus:ring-1"
              style={{ background: 'var(--elevated)', border: `1px solid ${error ? '#ef4444' : 'var(--border)'}`, '--tw-ring-color': '#eab308' } as React.CSSProperties}
              onChange={(e) => { setConfirmPassword(e.target.value); setError('') }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
            />
            {error && (
              <div className="flex items-center gap-1.5 text-xs" style={{ color: '#ef4444' }}>
                <AlertCircle size={12} />
                {error}
              </div>
            )}
          </div>

          <button
            onClick={handleSubmit}
            disabled={loading || !currentPassword || !newPassword || !confirmPassword}
            className="w-full py-2.5 rounded-lg text-sm font-semibold text-white transition-all flex items-center justify-center gap-2"
            style={{
              background: !loading && currentPassword && newPassword && confirmPassword ? '#eab308' : 'rgba(234,179,8,0.3)',
              cursor: !loading && currentPassword && newPassword && confirmPassword ? 'pointer' : 'not-allowed',
            }}
          >
            {loading ? (<><Loader2 size={14} className="animate-spin" /> Salvando...</>) : (<><KeyRound size={14} /> Trocar senha</>)}
          </button>
        </div>

        <div
          className="px-8 py-4 flex items-center justify-end"
          style={{ borderTop: '1px solid var(--border)', background: 'var(--elevated)' }}
        >
          <button onClick={logout} className="text-[11px] text-t3 hover:text-t2 transition-colors">
            Sair
          </button>
        </div>
      </div>
    </div>
  )
}

export function ForcePasswordChangeGate({ children }: { children: React.ReactNode }) {
  const { tokens } = useAuthStore()

  if (tokens?.must_change_password) {
    return <ChangePasswordScreen />
  }

  return <>{children}</>
}
