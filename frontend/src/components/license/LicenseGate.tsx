import { useEffect, useState } from 'react'
import { KeyRound, ShieldCheck, AlertCircle, Loader2 } from 'lucide-react'
import { useLicenseStore } from '@/store/licenseStore'
import { useAuthStore } from '@/store/authStore'

const KEY_FORMAT = /^[A-Z0-9]{4}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$/

function formatKey(raw: string): string {
  const cleaned = raw.toUpperCase().replace(/[^A-Z0-9]/g, '')
  const groups = [4, 5, 5, 5, 5]
  let result = ''
  let pos = 0
  for (let i = 0; i < groups.length; i++) {
    const chunk = cleaned.slice(pos, pos + groups[i])
    if (!chunk) break
    if (result) result += '-'
    result += chunk
    pos += groups[i]
  }
  return result
}

function LicenseActivationScreen() {
  const [key, setKey]       = useState('')
  const [error, setError]   = useState('')
  const [loading, setLoading] = useState(false)
  const activate = useLicenseStore((s) => s.activate)
  const { logout } = useAuthStore()
  const { user } = useAuthStore()

  const handleChange = (v: string) => {
    setKey(formatKey(v))
    setError('')
  }

  const handleSubmit = async () => {
    if (!KEY_FORMAT.test(key)) {
      setError('Formato inválido. Use: XXXX-XXXXX-XXXXX-XXXXX-XXXXX')
      return
    }
    setLoading(true)
    setError('')
    try {
      await activate(key)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Chave inválida ou já utilizada.'
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
        {/* Header */}
        <div
          className="px-8 py-7 text-center"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-4"
            style={{ background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.2)' }}
          >
            <KeyRound size={22} style={{ color: '#3b82f6' }} />
          </div>
          <h1 className="text-base font-semibold text-t1">Ativação de Licença</h1>
          <p className="text-xs text-t3 mt-1">
            Insira a chave de licença fornecida pelo suporte
          </p>
        </div>

        {/* Body */}
        <div className="px-8 py-6 space-y-4">
          {user && (
            <p className="text-xs text-t3 text-center">
              Autenticado como <span className="text-t2 font-medium">{user.email}</span>
            </p>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-t2 uppercase tracking-wide">
              Chave de Licença
            </label>
            <input
              type="text"
              value={key}
              maxLength={28}
              className="w-full px-3 py-2.5 rounded-lg font-mono text-sm text-t1 placeholder:text-t3 outline-none focus:ring-1"
              style={{
                background: 'var(--elevated)',
                border: `1px solid ${error ? '#ef4444' : 'var(--border)'}`,
                '--tw-ring-color': '#3b82f6',
              } as React.CSSProperties}
              placeholder="XXXX-XXXXX-XXXXX-XXXXX-XXXXX"
              onChange={(e) => handleChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit() }}
              autoFocus
              spellCheck={false}
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
            disabled={loading || key.length < 28}
            className="w-full py-2.5 rounded-lg text-sm font-semibold text-white transition-all flex items-center justify-center gap-2"
            style={{
              background: key.length >= 28 && !loading ? '#3b82f6' : 'rgba(59,130,246,0.3)',
              cursor: key.length >= 28 && !loading ? 'pointer' : 'not-allowed',
            }}
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Validando...
              </>
            ) : (
              <>
                <ShieldCheck size={14} />
                Ativar Licença
              </>
            )}
          </button>
        </div>

        {/* Footer */}
        <div
          className="px-8 py-4 flex items-center justify-between"
          style={{ borderTop: '1px solid var(--border)', background: 'var(--elevated)' }}
        >
          <p className="text-[11px] text-t3">
            Problemas? Entre em contato com o suporte.
          </p>
          <button
            onClick={logout}
            className="text-[11px] text-t3 hover:text-t2 transition-colors"
          >
            Sair
          </button>
        </div>
      </div>
    </div>
  )
}

function LoadingScreen() {
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center" style={{ background: 'var(--bg)' }}>
      <Loader2 size={24} className="animate-spin" style={{ color: 'var(--text-3)' }} />
    </div>
  )
}

export function LicenseGate({ children }: { children: React.ReactNode }) {
  const { status, loading, checked, fetch, reset } = useLicenseStore()
  const { tokens } = useAuthStore()

  // Reset store when user logs out (token disappears)
  useEffect(() => {
    if (!tokens) reset()
  }, [tokens, reset])

  // Fetch on mount when authenticated
  useEffect(() => {
    if (tokens && !checked && !loading) fetch()
  }, [tokens, checked, loading, fetch])

  if (!tokens) return <>{children}</>
  if (!checked || loading) return <LoadingScreen />

  if (!status?.active) {
    return <LicenseActivationScreen />
  }

  return <>{children}</>
}
