import { useState, useEffect } from 'react'
import { ArrowRight, Check, Loader2, AlertTriangle, KeyRound, Server, Cloud } from 'lucide-react'
import { AddCameraWizard } from './AddCameraWizard'
import { api } from '@/services/api'
import toast from 'react-hot-toast'

interface Props {
  onComplete: () => void
}

// Dois modelos de deploy — exatamente como na imagem
const DEPLOYMENT_MODELS = [
  {
    id: 'managed',
    icon: Cloud,
    name: 'White Label (Managed)',
    subtitle: 'Cuidamos da sua infra',
    annual_price: 15000,
    storage: 'R$ 50/cam/mês (a partir de 7 dias)',
    storage_options: ['7 dias', '15 dias', '30 dias (por câmera)'],
    analytics: 'Pago por plugin/câmera/mês',
    analytics_detail: 'Analytics leves: a partir de R$ 6,90/dia\nAnalytics Pro: a partir de R$ 9,90/dia',
    extras: 'SLA Dedicado, Suporte Prioritário, Acesso à equipe de devs',
  },
  {
    id: 'self_hosted',
    icon: Server,
    name: 'White Label (Self-Hosted)',
    subtitle: 'Você cuida da sua infra',
    annual_price: 20000,
    storage: 'Por conta do cliente',
    storage_options: [],
    analytics: 'Por conta do cliente',
    analytics_detail: 'Você instala e gerencia os plugins de analytics',
    extras: 'Infra própria, total controle',
  },
]

export function OnboardingWizard({ onComplete }: Props) {
  const [step, setStep] = useState(0)
  const [accentColor, setAccentColor] = useState('#6366f1')
  const [systemName, setSystemName] = useState('VMS')
  const [showAddCamera, setShowAddCamera] = useState(false)
  const [cameraAdded, setCameraAdded] = useState(false)

  // License state
  const [selectedModel, setSelectedModel] = useState<string>('managed')
  const [licenseKey, setLicenseKey] = useState('')
  const [activating, setActivating] = useState(false)
  const [activationError, setActivationError] = useState('')

  useEffect(() => {
    document.documentElement.style.setProperty('--accent', accentColor)
  }, [accentColor])

  // Format: XXXX-XXXXX-XXXXX-XXXXX-XXXXX
  const handleKeyChange = (value: string) => {
    const cleaned = value.toUpperCase().replace(/[^A-Z0-9]/g, '')
    let formatted = ''
    const groups = [4, 5, 5, 5, 5]
    let idx = 0
    for (const len of groups) {
      if (idx >= cleaned.length) break
      if (formatted) formatted += '-'
      formatted += cleaned.slice(idx, idx + len)
      idx += len
    }
    setLicenseKey(formatted)
    setActivationError('')
  }

  const handleActivate = async () => {
    if (licenseKey.length < 28) {
      setActivationError('License key incompleta')
      return
    }
    setActivating(true)
    setActivationError('')
    try {
      const { data } = await api.post('/api/v1/billing/activate', { license_key: licenseKey })
      toast.success(`${data.deployment_model === 'managed' ? 'Managed' : 'Self-Hosted'} ativado! ${data.licenses_created} licenças criadas.`)
      localStorage.setItem('vms_onboarding_billing_done', '1')
      setStep(2)
    } catch (err: any) {
      const msg = err.response?.data?.detail ?? 'Erro ao ativar'
      setActivationError(msg)
      toast.error(msg)
    } finally {
      setActivating(false)
    }
  }

  const COLORS = ['#6366f1', '#3b82f6', '#0ea5e9', '#14b8a6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6']
  const totalSteps = 4

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto" style={{ background: 'var(--bg)' }}>
      <div className="w-full max-w-lg space-y-6 my-8">

        {/* Step counter */}
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {Array.from({ length: totalSteps }).map((_, i) => (
              <div key={i} className="h-1 rounded-full transition-all"
                style={{ width: i === step ? '24px' : '8px', background: i <= step ? 'var(--accent)' : 'var(--border)' }} />
            ))}
          </div>
          <span className="text-xs text-t3 ml-1">{step + 1} / {totalSteps}</span>
        </div>

        {/* ── Passo 0: Welcome ── */}
        {step === 0 && (
          <div className="space-y-5">
            <div>
              <h1 className="text-xl font-bold text-t1">Bem-vindo ao VMS</h1>
              <p className="text-sm text-t2 mt-1">Configure o sistema em poucas etapas.</p>
            </div>
            <div className="space-y-2">
              {['Definir identidade', 'Escolher modelo e ativar licença', 'Adicionar câmera', 'Dashboard'].map((item, i) => (
                <div key={i} className="flex items-center gap-3 text-sm text-t2">
                  <span className="text-xs font-mono text-t3 w-4">{String(i + 1).padStart(2, '0')}</span>
                  {item}
                </div>
              ))}
            </div>
            <button className="btn btn-primary w-full" onClick={() => setStep(1)}>
              Começar <ArrowRight size={14} className="ml-1" />
            </button>
          </div>
        )}

        {/* ── Passo 1: Identidade ── */}
        {step === 1 && (
          <div className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-t1">Identidade</h2>
              <p className="text-sm text-t2 mt-1">Nome e cor do sistema.</p>
            </div>
            <div className="space-y-4">
              <div>
                <label className="label">Nome do sistema</label>
                <input className="input" placeholder="VMS — Empresa XYZ" value={systemName} onChange={(e) => setSystemName(e.target.value)} />
              </div>
              <div>
                <label className="label">Cor primária</label>
                <div className="flex gap-2 mt-1.5 flex-wrap">
                  {COLORS.map((c) => (
                    <button key={c} onClick={() => setAccentColor(c)}
                      className="w-6 h-6 rounded-md transition-transform"
                      style={{ background: c, outline: accentColor === c ? `2px solid ${c}` : 'none', outlineOffset: '2px' }} />
                  ))}
                  <input type="color" value={accentColor} onChange={(e) => setAccentColor(e.target.value)} className="w-6 h-6 rounded-md cursor-pointer border-0 bg-transparent p-0" />
                </div>
              </div>
            </div>
            <button className="btn btn-primary w-full" onClick={() => setStep(2)}>
              Próximo <ArrowRight size={14} className="ml-1" />
            </button>
          </div>
        )}

        {/* ── Passo 2: Modelo + Licença ── */}
        {step === 2 && (
          <div className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-t1">Escolha o Modelo</h2>
              <p className="text-sm text-t2 mt-1">Selecione o modelo de deploy e insira a license key.</p>
            </div>

            {/* Modelo cards */}
            <div className="grid grid-cols-1 gap-3">
              {DEPLOYMENT_MODELS.map((model) => {
                const Icon = model.icon
                const isSelected = selectedModel === model.id
                return (
                  <button
                    key={model.id}
                    className={`text-left card p-4 transition-all border-2 ${isSelected ? 'border-t1' : 'border-transparent hover:border-border'}`}
                    onClick={() => setSelectedModel(model.id)}
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: isSelected ? 'var(--accent)' : 'var(--elevated)' }}>
                        <Icon size={20} className={isSelected ? 'text-white' : 'text-t2'} />
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-bold text-t1">{model.name}</p>
                          {isSelected && <Check size={16} className="text-t1" />}
                        </div>
                        <p className="text-xs text-t3">{model.subtitle}</p>
                        <p className="text-lg font-bold text-t1 mt-2">
                          R$ {model.annual_price.toLocaleString('pt-BR')}<span className="text-xs font-normal text-t3">/ano</span>
                        </p>
                      </div>
                    </div>

                    {/* Detalhes expansíveis */}
                    {isSelected && (
                      <div className="mt-3 pt-3 border-t text-xs text-t3 space-y-1" style={{ borderColor: 'var(--border)' }}>
                        <p><span className="text-t2 font-medium">Licença inclui:</span> Streaming, Câmeras, Users, Relatórios, Acesso total, LPR (webhook)</p>
                        <p><span className="text-t2 font-medium">Storage ({model.id === 'managed' ? 'obrigatório' : 'por conta do cliente'}):</span> {model.storage}</p>
                        {model.storage_options.length > 0 && (
                          <div className="flex gap-2 mt-1">
                            {model.storage_options.map((opt) => (
                              <span key={opt} className="px-2 py-0.5 rounded bg-elevated text-t2">{opt}</span>
                            ))}
                          </div>
                        )}
                        <p><span className="text-t2 font-medium">Analytics:</span> {model.analytics}</p>
                        <p className="whitespace-pre-line">{model.analytics_detail}</p>
                        {model.extras && <p className="text-t2 mt-1">{model.extras}</p>}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>

            {/* License Key input */}
            <div>
              <label className="label">License Key</label>
              <div className="relative">
                <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-t3" />
                <input
                  className="input pl-9 font-mono text-lg tracking-widest text-center uppercase"
                  placeholder="XXXX-XXXXX-XXXXX-XXXXX-XXXXX"
                  value={licenseKey}
                  onChange={(e) => handleKeyChange(e.target.value)}
                  maxLength={28}
                  autoFocus
                />
              </div>
              {activationError && (
                <div className="flex items-center gap-2 mt-2 text-xs text-red-400">
                  <AlertTriangle size={13} /> {activationError}
                </div>
              )}
            </div>

            <button className="btn btn-primary w-full flex items-center justify-center gap-2" onClick={handleActivate} disabled={licenseKey.length < 28 || activating}>
              {activating ? <><Loader2 size={16} className="animate-spin" /> Ativando...</> : <><KeyRound size={16} /> Ativar Sistema</>}
            </button>

            <button className="btn btn-ghost w-full text-sm" onClick={() => setStep(3)}>Ativar depois</button>
          </div>
        )}

        {/* ── Passo 3: Primeira câmera ── */}
        {step === 3 && (
          <div className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-t1">Primeira câmera</h2>
              <p className="text-sm text-t2 mt-1">Conecte o primeiro dispositivo.</p>
            </div>
            {cameraAdded ? (
              <div className="space-y-3">
                <p className="text-sm text-t2 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: 'var(--success)' }} /> Câmera adicionada.
                </p>
                <button className="btn btn-primary w-full" onClick={() => { localStorage.setItem('vms_onboarding_complete', '1'); onComplete() }}>
                  Ir para o Dashboard <Check size={14} className="ml-1" />
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <button className="btn btn-primary w-full" onClick={() => setShowAddCamera(true)}>Adicionar câmera</button>
                <button className="btn btn-ghost w-full text-sm" onClick={() => { localStorage.setItem('vms_onboarding_complete', '1'); onComplete() }}>Pular por enquanto</button>
              </div>
            )}
          </div>
        )}

      </div>

      <AddCameraWizard open={showAddCamera} onClose={() => setShowAddCamera(false)} onCreated={() => { setShowAddCamera(false); setCameraAdded(true) }} defaultProtocol="rtmp_push" />
    </div>
  )
}
