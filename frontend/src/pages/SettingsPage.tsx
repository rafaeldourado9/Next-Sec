import { useState, useRef, useEffect, useCallback } from 'react'
import { Save, Palette, Upload, Building2, MessageCircle, Loader2, CheckCircle2 } from 'lucide-react'
import { useThemeStore } from '@/store/themeStore'
import { api } from '@/services/api'
import { whatsappService, type WhatsAppStatus } from '@/services/whatsapp'
import toast from 'react-hot-toast'

const ACCENT_PRESETS = [
  { label: 'Azul',    color: '#3B82F6' },
  { label: 'Violeta', color: '#8B5CF6' },
  { label: 'Verde',   color: '#22C55E' },
  { label: 'Roxo',    color: '#A855F7' },
  { label: 'Rosa',    color: '#EC4899' },
  { label: 'Laranja', color: '#F97316' },
  { label: 'Cyan',    color: '#06B6D4' },
  { label: 'Amarelo', color: '#EAB308' },
]

interface Branding {
  company_name: string
  cnpj: string
  company_address: string
  logo_url: string
}

export function SettingsPage() {
  const { accentColor, systemName, logoUrl, setTheme } = useThemeStore()

  const [name, setName]         = useState(systemName)
  const [accent, setAccent]     = useState(accentColor)
  const [logo, setLogo]         = useState(logoUrl ?? '')
  const [saving, setSaving]     = useState(false)
  const fileInputRef            = useRef<HTMLInputElement>(null)

  const [branding, setBranding]         = useState<Branding>({ company_name: '', cnpj: '', company_address: '', logo_url: '' })
  const [savingBranding, setSavingBranding] = useState(false)

  const [waStatus, setWaStatus]   = useState<WhatsAppStatus | null>(null)
  const [waQr, setWaQr]           = useState<string | null>(null)
  const [waLoading, setWaLoading] = useState(false)

  const refreshWaStatus = useCallback(async () => {
    try {
      const status = await whatsappService.getStatus()
      setWaStatus(status)
      if (status.connected) setWaQr(null)
      return status
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    refreshWaStatus()
  }, [refreshWaStatus])

  // Enquanto tem QR pendente, verifica a cada 3s se já conectou
  useEffect(() => {
    if (!waQr || waStatus?.connected) return
    const interval = setInterval(async () => {
      const status = await refreshWaStatus()
      if (status?.connected) toast.success('WhatsApp conectado!')
    }, 3000)
    return () => clearInterval(interval)
  }, [waQr, waStatus?.connected, refreshWaStatus])

  // QR do WhatsApp expira rápido (~60s) — gera um novo periodicamente enquanto pendente
  useEffect(() => {
    if (!waQr || waStatus?.connected) return
    const interval = setInterval(async () => {
      const { qr } = await whatsappService.connect().catch(() => ({ qr: null }))
      if (qr) setWaQr(qr)
    }, 45000)
    return () => clearInterval(interval)
  }, [waQr, waStatus?.connected])

  const handleWaConnect = async () => {
    setWaLoading(true)
    try {
      const { qr } = await whatsappService.connect()
      setWaQr(qr)
      if (!qr) toast.error('Arcanum não retornou QR — tente novamente')
    } catch {
      toast.error('Erro ao conectar com o Arcanum')
    } finally {
      setWaLoading(false)
    }
  }

  const handleWaDisconnect = async () => {
    if (!confirm('Desconectar o WhatsApp? Alertas por WhatsApp param de ser enviados.')) return
    setWaLoading(true)
    try {
      await whatsappService.disconnect()
      setWaQr(null)
      await refreshWaStatus()
      toast.success('WhatsApp desconectado')
    } catch {
      toast.error('Erro ao desconectar')
    } finally {
      setWaLoading(false)
    }
  }

  useEffect(() => {
    api.get('/iam/branding')
      .then(({ data }) => setBranding({
        company_name:    data.company_name    ?? '',
        cnpj:            data.cnpj            ?? '',
        company_address: data.company_address ?? '',
        logo_url:        data.logo_url        ?? '',
      }))
      .catch(() => {})
  }, [])

  const handleSaveBranding = async () => {
    setSavingBranding(true)
    try {
      await api.patch('/iam/branding', {
        company_name:    branding.company_name    || null,
        cnpj:            branding.cnpj            || null,
        company_address: branding.company_address || null,
        logo_url:        branding.logo_url        || null,
      })
      toast.success('Dados da empresa salvos')
    } catch {
      toast.error('Erro ao salvar dados da empresa')
    } finally {
      setSavingBranding(false)
    }
  }

  const handleLogoFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => setLogo(ev.target?.result as string)
    reader.readAsDataURL(file)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      setTheme({ accentColor: accent, systemName: name, logoUrl: logo || null })
      toast.success('Configurações salvas')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6 animate-fade-in">
      <div>
        <p className="text-sm font-semibold text-t1 mb-1">Aparência do Sistema</p>
        <p className="text-xs text-t3">Personalize o nome, logo e cor do sistema</p>
      </div>

      {/* System name */}
      <div className="card p-5 space-y-4">
        <p className="text-xs font-semibold text-t2 uppercase tracking-wide">Identidade</p>

        <div>
          <label className="label">Nome do Sistema</label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="VMS"
          />
        </div>

        <div>
          <label className="label">Logo (upload ou URL)</label>
          <div className="flex gap-2">
            <input
              className="input flex-1"
              value={logo}
              onChange={(e) => setLogo(e.target.value)}
              placeholder="https://exemplo.com/logo.png"
            />
            <button
              type="button"
              className="btn btn-ghost gap-1.5 shrink-0"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={14} />Upload
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleLogoFile}
            />
          </div>
        </div>

        {logo && (
          <div className="flex items-center gap-3">
            <p className="text-xs text-t3">Preview:</p>
            <img
              src={logo}
              alt="Logo preview"
              className="h-10 w-auto object-contain rounded"
              onError={() => toast.error('Logo inválido')}
            />
            <button
              type="button"
              className="text-xs text-danger hover:underline"
              onClick={() => setLogo('')}
            >
              Remover
            </button>
          </div>
        )}
      </div>

      {/* Accent color */}
      <div className="card p-5 space-y-4">
        <p className="text-xs font-semibold text-t2 uppercase tracking-wide flex items-center gap-2">
          <Palette size={14} />Cor de Destaque
        </p>

        <div className="flex flex-wrap gap-2">
          {ACCENT_PRESETS.map(({ label, color }) => (
            <button
              key={color}
              title={label}
              onClick={() => setAccent(color)}
              className="w-8 h-8 rounded-lg transition-all border-2"
              style={{
                background: color,
                borderColor: accent === color ? 'white' : 'transparent',
                transform: accent === color ? 'scale(1.15)' : 'scale(1)',
              }}
            />
          ))}
        </div>

        <div>
          <label className="label">Cor Personalizada</label>
          <div className="flex items-center gap-3">
            <input
              type="color"
              className="w-10 h-10 rounded-lg cursor-pointer border-0 p-0.5"
              style={{ background: 'var(--elevated)' }}
              value={accent}
              onChange={(e) => setAccent(e.target.value)}
            />
            <input
              className="input font-mono"
              value={accent}
              onChange={(e) => setAccent(e.target.value)}
              placeholder="#3B82F6"
            />
          </div>
        </div>

        {/* Preview */}
        <div className="flex items-center gap-3">
          <p className="text-xs text-t3">Preview:</p>
          <button
            className="btn text-white text-xs"
            style={{ background: accent }}
          >
            Botão Primário
          </button>
          <div
            className="w-6 h-6 rounded-md"
            style={{ background: accent }}
          />
        </div>
      </div>

      <button
        className="btn btn-primary gap-2"
        onClick={handleSave}
        disabled={saving}
      >
        <Save size={16} />{saving ? 'Salvando...' : 'Salvar Aparência'}
      </button>

      {/* Dados da empresa — aparecem nos PDFs de relatório */}
      <div>
        <p className="text-sm font-semibold text-t1 mb-1 flex items-center gap-2">
          <Building2 size={16} />Dados da Empresa (PDF)
        </p>
        <p className="text-xs text-t3">Estas informações aparecem no cabeçalho e rodapé dos relatórios em PDF</p>
      </div>

      <div className="card p-5 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Nome da Empresa</label>
            <input
              className="input"
              value={branding.company_name}
              onChange={(e) => setBranding((b) => ({ ...b, company_name: e.target.value }))}
              placeholder="Empresa de Segurança Ltda"
            />
          </div>
          <div>
            <label className="label">CNPJ</label>
            <input
              className="input font-mono"
              value={branding.cnpj}
              onChange={(e) => setBranding((b) => ({ ...b, cnpj: e.target.value }))}
              placeholder="00.000.000/0001-00"
            />
          </div>
        </div>

        <div>
          <label className="label">Endereço</label>
          <input
            className="input"
            value={branding.company_address}
            onChange={(e) => setBranding((b) => ({ ...b, company_address: e.target.value }))}
            placeholder="Rua Exemplo, 123 — São Paulo, SP"
          />
        </div>

        <div>
          <label className="label">URL do Logo (para PDFs)</label>
          <input
            className="input"
            value={branding.logo_url}
            onChange={(e) => setBranding((b) => ({ ...b, logo_url: e.target.value }))}
            placeholder="https://exemplo.com/logo.png"
          />
          <p className="text-xs text-t3 mt-1">Use uma URL pública acessível pelo servidor de relatórios</p>
        </div>

        <button
          className="btn btn-primary gap-2"
          onClick={handleSaveBranding}
          disabled={savingBranding}
        >
          <Save size={16} />{savingBranding ? 'Salvando...' : 'Salvar Dados da Empresa'}
        </button>
      </div>

      {/* WhatsApp — alertas para contatos via Arcanum */}
      <div>
        <p className="text-sm font-semibold text-t1 mb-1 flex items-center gap-2">
          <MessageCircle size={16} />WhatsApp
        </p>
        <p className="text-xs text-t3">Conecte um número para enviar alertas aos contatos cadastrados</p>
      </div>

      <div className="card p-5 space-y-4">
        {waStatus?.connected ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-t1">
              <CheckCircle2 size={16} className="text-success" />
              WhatsApp conectado
            </div>
            <button
              className="btn btn-ghost text-danger gap-2"
              onClick={handleWaDisconnect}
              disabled={waLoading}
            >
              {waLoading ? <Loader2 size={14} className="animate-spin" /> : 'Desconectar'}
            </button>
          </div>
        ) : waQr ? (
          <div className="flex flex-col items-center gap-3 py-2">
            <img src={waQr} alt="QR Code WhatsApp" className="w-56 h-56 rounded-lg border" style={{ borderColor: 'var(--border)' }} />
            <p className="text-xs text-t3 text-center max-w-xs">
              Abra o WhatsApp no celular → Configurações → Dispositivos conectados → Conectar dispositivo
            </p>
          </div>
        ) : (
          <div className="flex items-center justify-between">
            <p className="text-xs text-t3">Nenhum número conectado ainda</p>
            <button
              className="btn btn-primary gap-2"
              onClick={handleWaConnect}
              disabled={waLoading}
            >
              {waLoading ? <Loader2 size={14} className="animate-spin" /> : <MessageCircle size={14} />}
              Conectar WhatsApp
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
