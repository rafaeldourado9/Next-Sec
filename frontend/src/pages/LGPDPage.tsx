import { useEffect, useState, useCallback } from 'react'
import { Shield, Eye, EyeOff, FileText, Download, AlertTriangle } from 'lucide-react'
import { lgpdService, type LgpdStatus, type RetentionPolicy } from '@/services/lgpd'
import { PageSpinner } from '@/components/ui/Spinner'
import { Modal } from '@/components/ui/Modal'
import toast from 'react-hot-toast'

const DATA_TYPE_LABELS: Record<string, string> = {
  video: 'Vídeo',
  alpr: 'Placas (ALPR)',
  face: 'Reconhecimento Facial',
  audit: 'Logs de Auditoria',
  analytics: 'Eventos de Analytics',
}

const COMPLIANCE_LABELS: Record<string, { label: string; color: string }> = {
  full:    { label: 'Completo',   color: '#22c55e' },
  partial: { label: 'Parcial',    color: '#f59e0b' },
  minimal: { label: 'Mínimo',     color: '#ef4444' },
}

export function LGPDPage() {
  const [status, setStatus]           = useState<LgpdStatus | null>(null)
  const [policies, setPolicies]       = useState<RetentionPolicy[]>([])
  const [defaults, setDefaults]       = useState<Record<string, number>>({})
  const [loading, setLoading]         = useState(true)
  const [showConsentModal, setShowConsentModal] = useState(false)
  const [consentDataType, setConsentDataType] = useState('face')
  const [consentAccepted, setConsentAccepted] = useState(false)
  const [consenting, setConsenting]   = useState(false)
  const [retentionEdits, setRetentionEdits] = useState<Record<string, number>>({})

  const loadData = useCallback(() => {
    setLoading(true)
    Promise.all([
      lgpdService.getStatus(),
      lgpdService.getRetentionPolicies(),
    ])
      .then(([s, p]) => {
        setStatus(s)
        setPolicies(p.policies)
        setDefaults(p.defaults)
        // Init edits with current values
        const edits: Record<string, number> = {}
        p.policies.forEach((pol) => { edits[pol.data_type] = pol.retention_days })
        setRetentionEdits(edits)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleGrantConsent = async () => {
    if (!consentAccepted) return
    setConsenting(true)
    try {
      await lgpdService.grantConsent(consentDataType, 'Concordo com o processamento de dados biométricos conforme LGPD Art. 11')
      toast.success('Consentimento registrado')
      setShowConsentModal(false)
      setConsentAccepted(false)
      loadData()
    } catch {
      toast.error('Erro ao registrar consentimento')
    } finally {
      setConsenting(false)
    }
  }

  const handleSaveRetention = async (dataType: string) => {
    const days = retentionEdits[dataType]
    if (!days || days < 1) return
    try {
      await lgpdService.setRetentionPolicy(dataType, days)
      toast.success(`Retenção de ${DATA_TYPE_LABELS[dataType]} atualizada para ${days} dias`)
      loadData()
    } catch {
      toast.error('Erro ao atualizar retenção')
    }
  }

  const handleGenerateRipd = async () => {
    try {
      toast.loading('Gerando RIPD...', { id: 'ripd' })
      await lgpdService.generateRipd()
      toast.success('RIPD gerado com sucesso!', { id: 'ripd' })
    } catch {
      toast.error('Erro ao gerar RIPD', { id: 'ripd' })
    }
  }

  const handleDataExport = async () => {
    try {
      await lgpdService.requestDataExport('export', 'Exportação de dados pessoais do titular')
      toast.success('Solicitação de exportação registrada')
    } catch {
      toast.error('Erro ao solicitar exportação')
    }
  }

  if (loading) return <PageSpinner />
  if (!status) return <div className="py-16 text-center text-sm text-t3">Não foi possível carregar informações LGPD.</div>

  const compliance = COMPLIANCE_LABELS[status.compliance_level] ?? COMPLIANCE_LABELS.minimal

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div>
        <p className="text-sm font-semibold text-t1">LGPD & Compliance</p>
        <p className="text-xs text-t3 mt-0.5">Proteção de dados pessoais — Lei Geral de Proteção de Dados (Lei 13.709/2018)</p>
      </div>

      {/* Status overview */}
      <div className="grid grid-cols-3 gap-3">
        <div className="card px-4 py-3">
          <p className="text-xs text-t3 mb-1">Nível de Compliance</p>
          <span
            className="inline-flex items-center gap-1.5 text-xs font-medium px-1.5 py-0.5 rounded-full"
            style={{ color: compliance.color, background: `${compliance.color}18` }}
          >
            {compliance.label}
          </span>
        </div>
        <div className="card px-4 py-3">
          <p className="text-xs text-t3 mb-1">Políticas Configuradas</p>
          <p className="text-xl font-bold text-t1 tabular-nums">{status.policies_configured}</p>
        </div>
        <div className="card px-4 py-3">
          <p className="text-xs text-t3 mb-1">Face Recognition</p>
          <p className="text-xs text-t2 mt-1">
            {status.face_recognition_requires_consent
              ? '⚠️ Requer consentimento'
              : '✅ Consentimento ativo'}
          </p>
        </div>
      </div>

      {/* Face Recognition consent */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Shield size={18} className="text-t2" />
            <p className="text-sm font-semibold text-t1">Reconhecimento Facial — Consentimento LGPD</p>
          </div>
          <button
            className="btn btn-primary text-xs gap-1.5"
            onClick={() => { setConsentDataType('face'); setShowConsentModal(true) }}
          >
            {status.face_recognition_requires_consent ? (
              <>
                <Eye size={14} /> Conceder Consentimento
              </>
            ) : (
              <>
                <EyeOff size={14} /> Revogar
              </>
            )}
          </button>
        </div>
        <p className="text-xs text-t3">
          O reconhecimento facial requer consentimento explícito conforme LGPD Art. 11.
          Ao ativar, você concorda com o processamento de dados biométricos.
        </p>
      </div>

      {/* Retention policies */}
      <div className="card p-4">
        <p className="text-sm font-semibold text-t1 mb-3">Políticas de Retenção</p>
        <div className="space-y-3">
          {Object.entries(DATA_TYPE_LABELS).map(([key, label]) => {
            const policy = policies.find((p) => p.data_type === key)
            const currentDays = policy?.retention_days ?? defaults[key] ?? 7
            const isEditing = retentionEdits[key] !== undefined && retentionEdits[key] !== currentDays

            return (
              <div key={key} className="flex items-center gap-4 p-3 rounded-lg bg-elevated">
                <div className="flex-1">
                  <p className="text-sm text-t1">{label}</p>
                  <p className="text-xs text-t3">
                    {policy ? `${policy.retention_days} dias configurado` : `Padrão: ${defaults[key] ?? 7} dias`}
                    {policy?.anonymize_instead_of_delete !== false && ' · Anonimização ativa'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    className="input w-20 text-center text-sm"
                    min={1}
                    defaultValue={currentDays}
                    onChange={(e) => setRetentionEdits((prev) => ({ ...prev, [key]: parseInt(e.target.value) || 1 }))}
                  />
                  <span className="text-xs text-t3">dias</span>
                  {isEditing && (
                    <button
                      className="btn btn-primary text-xs"
                      onClick={() => handleSaveRetention(key)}
                    >
                      Salvar
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Rights of the data subject */}
      <div className="card p-4">
        <p className="text-sm font-semibold text-t1 mb-3">Direitos do Titular (Art. 18 LGPD)</p>
        <div className="grid grid-cols-2 gap-3">
          <button className="card p-3 flex items-center gap-3 hover:bg-elevated transition" onClick={handleDataExport}>
            <Download size={18} className="text-t2" />
            <div className="text-left">
              <p className="text-sm text-t1">Exportar Meus Dados</p>
              <p className="text-xs text-t3">Solicitar cópia dos dados pessoais</p>
            </div>
          </button>
          <button className="card p-3 flex items-center gap-3 hover:bg-elevated transition" onClick={handleGenerateRipd}>
            <FileText size={18} className="text-t2" />
            <div className="text-left">
              <p className="text-sm text-t1">Gerar RIPD</p>
              <p className="text-xs text-t3">Relatório de Impacto à Proteção de Dados</p>
            </div>
          </button>
        </div>
      </div>

      {/* Warning if minimal compliance */}
      {status.compliance_level === 'minimal' && (
        <div className="card p-4 flex items-start gap-3" style={{ background: '#ef44440d', borderColor: '#ef444430' }}>
          <AlertTriangle size={18} className="text-red-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-t1">Compliance mínimo</p>
            <p className="text-xs text-t3 mt-0.5">
              Configure políticas de retenção para todos os tipos de dados para atingir nível completo de compliance.
            </p>
          </div>
        </div>
      )}

      {/* Consent modal */}
      <Modal
        open={showConsentModal}
        onClose={() => { setShowConsentModal(false); setConsentAccepted(false) }}
        title="Consentimento LGPD — Reconhecimento Facial"
        size="md"
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => { setShowConsentModal(false); setConsentAccepted(false) }}>Cancelar</button>
            <button
              className="btn btn-primary"
              onClick={handleGrantConsent}
              disabled={!consentAccepted || consenting}
            >
              {consenting ? 'Registrando...' : 'Confirmar Consentimento'}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="card p-4 bg-elevated">
            <p className="text-sm text-t1 font-medium mb-2">Termo de Consentimento</p>
            <p className="text-xs text-t3 leading-relaxed">
              Em conformidade com a <strong className="text-t2">Lei Geral de Proteção de Dados (LGPD — Lei 13.709/2018)</strong>,
              especificamente o <strong className="text-t2">Art. 11</strong> sobre tratamento de dados pessoais sensíveis,
              declaro que fui informado(a) sobre:
            </p>
            <ul className="text-xs text-t3 mt-2 space-y-1 list-disc list-inside">
              <li>A finalidade do tratamento de dados biométricos (reconhecimento facial)</li>
              <li>Os tipos de dados coletados e o período de retenção (30 dias padrão)</li>
              <li>Quem tem acesso aos dados (administradores do tenant)</li>
              <li>As medidas de segurança implementadas (criptografia, audit trail)</li>
              <li>Meus direitos como titular (acesso, correção, anonimização, revogação)</li>
            </ul>
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={consentAccepted}
              onChange={(e) => setConsentAccepted(e.target.checked)}
              className="w-4 h-4 rounded"
            />
            <span className="text-sm text-t1">
              Li e concordo com o processamento de dados biométricos conforme descrito acima.
            </span>
          </label>
        </div>
      </Modal>
    </div>
  )
}
