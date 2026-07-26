import { useEffect, useRef, useState } from 'react'
import { Plus, Trash2, ScanFace, ShieldCheck } from 'lucide-react'
import { format } from 'date-fns'
import { watchlistService, type FaceProfile } from '@/services/watchlist'
import { lgpdService } from '@/services/lgpd'
import { PageSpinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import { usePermission } from '@/hooks/usePermission'
import toast from 'react-hot-toast'

export function WatchlistPage() {
  const { isAdmin } = usePermission()
  const [profiles, setProfiles] = useState<FaceProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [image, setImage] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [consentBlocked, setConsentBlocked] = useState(false)
  const [enablingConsent, setEnablingConsent] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const load = () => {
    watchlistService.list()
      .then(setProfiles)
      .catch(() => setProfiles([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const resetForm = () => {
    setName('')
    setImage(null)
    setPreviewUrl(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleImageSelect = (file: File | null) => {
    setImage(file)
    setPreviewUrl(file ? URL.createObjectURL(file) : null)
  }

  const handleCreate = async () => {
    if (!name.trim() || !image) return
    setCreating(true)
    setConsentBlocked(false)
    try {
      await watchlistService.create(name.trim(), image)
      toast.success('Rosto cadastrado na watchlist')
      setShowCreate(false)
      resetForm()
      load()
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 401) {
        setConsentBlocked(true)
        toast.error('Reconhecimento facial não habilitado para este tenant')
      } else {
        toast.error('Erro ao cadastrar rosto')
      }
    } finally {
      setCreating(false)
    }
  }

  const handleEnableConsent = async () => {
    setEnablingConsent(true)
    try {
      await lgpdService.grantConsent('face', 'Consentimento para reconhecimento facial — watchlist Next Sec')
      toast.success('Reconhecimento facial habilitado')
      setConsentBlocked(false)
    } catch {
      toast.error('Erro ao habilitar reconhecimento facial')
    } finally {
      setEnablingConsent(false)
    }
  }

  const handleDelete = async (profile: FaceProfile) => {
    if (!confirm(`Remover "${profile.name}" da watchlist?`)) return
    try {
      await watchlistService.del(profile.id)
      toast.success('Removido da watchlist')
      load()
    } catch {
      toast.error('Erro ao remover')
    }
  }

  if (loading) return <PageSpinner />

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-t1">Watchlist facial</p>
          <p className="text-xs text-t3 mt-0.5">
            Rostos cadastrados para reconhecimento facial nas zonas configuradas
          </p>
        </div>
        <button className="btn btn-primary gap-2" onClick={() => setShowCreate(true)}>
          <Plus size={16} />Cadastrar Rosto
        </button>
      </div>

      <div className="card p-3 flex items-start gap-2 text-xs text-t3" style={{ background: 'var(--elevated)' }}>
        <ShieldCheck size={14} className="text-accent shrink-0 mt-0.5" />
        <p>
          Dado biométrico — requer consentimento LGPD ativo (data_type <code>face</code>).
          Sem consentimento, o cadastro é bloqueado e nenhuma zona de reconhecimento facial processa vídeo.
        </p>
      </div>

      {profiles.length === 0 ? (
        <div className="card p-12 text-center">
          <ScanFace size={32} className="text-t3 mx-auto mb-3 opacity-30" />
          <p className="text-t3 text-sm">Nenhum rosto cadastrado</p>
          <button className="btn btn-ghost text-xs mt-3" onClick={() => setShowCreate(true)}>
            Cadastrar primeiro rosto
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {profiles.map((profile) => (
            <div key={profile.id} className="card p-4 space-y-3">
              <div className="flex items-center gap-2">
                <ScanFace size={18} className="text-t2" />
                <p className="text-sm font-semibold text-t1 truncate">{profile.name}</p>
              </div>
              <div className="flex items-center justify-between pt-2 border-t text-xs text-t3" style={{ borderColor: 'var(--border)' }}>
                <span>{format(new Date(profile.created_at), 'dd/MM/yyyy')}</span>
                {isAdmin && (
                  <button className="btn btn-ghost w-7 h-7 p-0 text-danger" onClick={() => handleDelete(profile)} title="Remover">
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={showCreate}
        onClose={() => { setShowCreate(false); resetForm(); setConsentBlocked(false) }}
        title="Cadastrar Rosto"
        size="sm"
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancelar</button>
            <button
              className="btn btn-primary"
              onClick={handleCreate}
              disabled={creating || !name.trim() || !image}
            >
              {creating ? 'Cadastrando...' : 'Cadastrar'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {consentBlocked && (
            <div className="card p-3 space-y-2" style={{ background: 'var(--elevated)' }}>
              <p className="text-xs text-t2">
                Este tenant ainda não tem consentimento LGPD para reconhecimento facial.
              </p>
              <button
                className="btn btn-primary text-xs w-full"
                onClick={handleEnableConsent}
                disabled={enablingConsent}
              >
                {enablingConsent ? 'Habilitando...' : 'Habilitar reconhecimento facial'}
              </button>
            </div>
          )}
          <div>
            <label className="label">Nome *</label>
            <input
              className="input"
              placeholder="Ex: João Silva"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Foto de referência *</label>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="input"
              onChange={(e) => handleImageSelect(e.target.files?.[0] ?? null)}
            />
            {previewUrl && (
              <img src={previewUrl} alt="Prévia" className="mt-2 w-24 h-24 object-cover rounded-lg" />
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}
