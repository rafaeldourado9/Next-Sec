import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight, ArrowLeft, CheckCircle2, AlertTriangle,
  Copy, Check, Search, Globe2, Wifi, ChevronDown, ChevronUp,
  MapPin, Cpu, Move, VideoOff, Radio,
} from 'lucide-react'
import { Modal } from '@/components/ui/Modal'
import { Spinner } from '@/components/ui/Spinner'
import { useConnectionTest } from '@/hooks/useConnectionTest'
import { camerasService as camerasSvc, type DiscoveredCamera } from '@/services/cameras'
import type { StreamQuality } from '@/types'

type Protocol = 'rtmp_push' | 'onvif' | 'manual'

const STEPS = ['Método', 'Conexão', 'Detalhes', 'Qualidade', 'Revisão']

const QUALITY_OPTIONS: { value: StreamQuality; label: string; sub: string }[] = [
  { value: 'low',    label: '480p',    sub: '~0.5 Mbps · ~200 MB/h' },
  { value: 'medium', label: '720p',    sub: '~1.0 Mbps · ~450 MB/h' },
  { value: 'high',   label: '1080p',   sub: '~2.5 Mbps · ~1.1 GB/h' },
  { value: 'source', label: 'Original', sub: 'Resolução da câmera'   },
]

const RETENTION_OPTIONS = [
  { days: 5,  label: '5 dias'  },
  { days: 15, label: '15 dias' },
  { days: 30, label: '30 dias' },
]

interface DoneState {
  id: string
  rtmp_url?: string
  stream_key?: string
  snapshot_url?: string
}

interface AddCameraWizardProps {
  open: boolean
  onClose: () => void
  onCreated: () => void
  defaultProtocol?: Protocol
}

const INITIAL_FORM = {
  name: '', location: '', manufacturer: 'generic',
  retention_days: 5, stream_quality: 'high' as StreamQuality,
  onvif_ip: '', onvif_port: '80', onvif_username: 'admin', onvif_password: '',
  manual_url: '',
  ia_enabled: false,
  ptz_supported: false,
  latitude: '',
  longitude: '',
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="relative w-9 h-5 rounded-full transition-colors shrink-0"
      style={{ background: checked ? 'var(--accent)' : 'var(--border)' }}
    >
      <span
        className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform"
        style={{ transform: checked ? 'translateX(16px)' : 'translateX(0)' }}
      />
    </button>
  )
}

export function AddCameraWizard({ open, onClose, onCreated, defaultProtocol }: AddCameraWizardProps) {
  const [step, setStep]         = useState(0)
  const [protocol, setProtocol] = useState<Protocol>(defaultProtocol ?? 'rtmp_push')
  const [loading, setLoading]   = useState(false)
  const [copied, setCopied]     = useState<string | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [gpsOpen, setGpsOpen]   = useState(false)
  const [done, setDone]         = useState<DoneState | null>(null)
  const [snapshotLoading, setSnapshotLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Network scan state
  const [scanOpen, setScanOpen]         = useState(false)
  const [scanning, setScanning]         = useState(false)
  const [scanSubnet, setScanSubnet]     = useState('')
  const [discovered, setDiscovered]     = useState<DiscoveredCamera[]>([])

  const [form, setForm] = useState(INITIAL_FORM)

  const { result: connTest, testOnvif, reset: resetTest } = useConnectionTest()

  const isLast = step === STEPS.length - 1 && !done

  // Poll snapshot after camera created (skip for RTMP — no snapshot until stream starts)
  useEffect(() => {
    if (!done || done.snapshot_url || protocol === 'rtmp_push') return
    setSnapshotLoading(true)
    let tries = 0

    const poll = async () => {
      tries++
      try {
        const url = await camerasSvc.snapshot(done.id)
        if (url) {
          setDone((d) => d ? { ...d, snapshot_url: url } : d)
          setSnapshotLoading(false)
          return
        }
      } catch { /* ignore */ }
      if (tries < 4) {
        pollRef.current = setTimeout(poll, 2500)
      } else {
        setSnapshotLoading(false)
      }
    }

    pollRef.current = setTimeout(poll, 1500)
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [done?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (open && !done) {
      setStep(0)
      setProtocol(defaultProtocol ?? 'rtmp_push')
      resetTest()
      setHelpOpen(false)
      setGpsOpen(false)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const f = (k: string, v: unknown) => setForm((p) => ({ ...p, [k]: v }))

  const canProceed = () => {
    if (done) return true
    if (step === 1) {
      if (protocol === 'onvif')  return !!form.onvif_ip && !!form.onvif_password
      if (protocol === 'manual') return /^(rtsp|rtmp|http|https):\/\/.+/.test(form.manual_url)
    }
    if (step === 2) return form.name.trim().length >= 2
    return true
  }

  const handleCreate = async () => {
    setLoading(true)
    try {
      const lat = form.latitude  ? parseFloat(form.latitude)  : undefined
      const lng = form.longitude ? parseFloat(form.longitude) : undefined

      const cam = await camerasSvc.create({
        name:             form.name.trim(),
        location:         form.location.trim() || undefined,
        manufacturer:     form.manufacturer,
        retention_days:   form.retention_days,
        stream_quality:   form.stream_quality,
        stream_protocol:  protocol === 'manual' ? 'rtsp_pull' : protocol,
        rtsp_url:         protocol === 'manual' ? form.manual_url
                        : protocol === 'onvif'  ? (connTest.rtsp_url ?? undefined)
                        : undefined,
        onvif_url:        protocol === 'onvif' ? `http://${form.onvif_ip}:${form.onvif_port}/onvif/device_service` : undefined,
        onvif_username:   protocol === 'onvif' ? form.onvif_username : undefined,
        onvif_password:   protocol === 'onvif' ? form.onvif_password : undefined,
        ia_enabled:       form.ia_enabled,
        ptz_supported:    form.ptz_supported,
        latitude:         lat,
        longitude:        lng,
      })

      let rtmpInfo: { rtmp_url?: string; stream_key?: string } = {}
      if (protocol === 'rtmp_push') {
        try { rtmpInfo = await camerasSvc.rtmpConfig(cam.id) } catch { /* ok */ }
      }

      const snapshot_url = protocol === 'onvif' ? (connTest.snapshot_url ?? undefined) : undefined
      setDone({ id: cam.id, ...rtmpInfo, snapshot_url })
    } catch (err: unknown) {
      type ApiErr = { response?: { data?: { detail?: string; message?: string } } }
      const data = (err as ApiErr)?.response?.data
      alert(data?.detail || data?.message || 'Erro ao criar câmera')
    } finally {
      setLoading(false)
    }
  }

  const handleScan = async () => {
    setScanning(true)
    setDiscovered([])
    try {
      const result = await camerasSvc.discover({ subnet: scanSubnet.trim() || undefined })
      setDiscovered(result.cameras ?? [])
    } catch { /* ignore */ } finally {
      setScanning(false)
    }
  }

  const pickDiscovered = (cam: DiscoveredCamera) => {
    try {
      const url = new URL(cam.onvif_url)
      f('onvif_ip', url.hostname)
      f('onvif_port', url.port || '80')
      if (cam.manufacturer) f('manufacturer', cam.manufacturer.toLowerCase())
    } catch {
      f('onvif_ip', cam.ip)
    }
    setScanOpen(false)
    setDiscovered([])
  }

  const handleClose = () => {
    if (done) onCreated()
    if (pollRef.current) clearTimeout(pollRef.current)
    setStep(0); setDone(null); setSnapshotLoading(false)
    setForm(INITIAL_FORM)
    resetTest(); setHelpOpen(false); setGpsOpen(false)
    setScanOpen(false); setDiscovered([])
    onClose()
  }

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key); setTimeout(() => setCopied(null), 2000)
    })
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={done ? 'Câmera criada' : 'Adicionar câmera'}
      size="lg"
      disableBackdropClose
      footer={
        done ? (
          <button className="btn btn-primary w-full" onClick={handleClose}>
            Ir para câmeras
          </button>
        ) : (
          <div className="flex justify-between w-full">
            <button
              className="btn btn-ghost text-sm"
              onClick={step === 0 ? handleClose : () => { setStep((s) => s - 1); resetTest() }}
              disabled={loading}
            >
              {step === 0 ? 'Cancelar' : <><ArrowLeft size={14} className="mr-1" />Voltar</>}
            </button>
            {isLast ? (
              <button className="btn btn-primary text-sm" onClick={handleCreate} disabled={loading || !canProceed()}>
                {loading ? <Spinner size="sm" /> : 'Criar câmera'}
              </button>
            ) : (
              <button className="btn btn-primary text-sm" onClick={() => setStep((s) => s + 1)} disabled={!canProceed()}>
                Próximo <ArrowRight size={14} className="ml-1" />
              </button>
            )}
          </div>
        )
      }
    >
      {/* Progress */}
      {!done && (
        <div className="flex items-center gap-1 mb-6">
          {STEPS.map((label, i) => (
            <div key={i} className="flex items-center flex-1 min-w-0">
              <div className="flex items-center gap-1.5 shrink-0">
                <div
                  className="w-5 h-5 rounded-full text-[10px] font-semibold flex items-center justify-center transition-colors"
                  style={
                    i < step  ? { background: 'var(--accent)', color: '#fff' }
                    : i === step ? { background: 'var(--accent)', color: '#fff', outline: '2px solid color-mix(in srgb, var(--accent) 30%, transparent)', outlineOffset: '1px' }
                    : { background: 'var(--elevated)', color: 'var(--t3)' }
                  }
                >
                  {i < step ? <CheckCircle2 size={11} /> : i + 1}
                </div>
                <span className={`text-[11px] hidden sm:block whitespace-nowrap ${i === step ? 'text-t1 font-medium' : i < step ? 'text-t2' : 'text-t3'}`}>
                  {label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div className="h-px flex-1 mx-2 transition-colors" style={{ background: i < step ? 'var(--accent)' : 'var(--border)' }} />
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Step 0: Método ── */}
      {!done && step === 0 && (
        <div className="space-y-2">
          {([
            { id: 'rtmp_push' as Protocol, icon: Wifi,   label: 'RTMP Push',  badge: 'Recomendado', desc: 'A câmera envia o stream para o VMS.' },
            { id: 'onvif'     as Protocol, icon: Search,  label: 'ONVIF',      badge: 'Automático',  desc: 'Descoberta automática via protocolo ONVIF.' },
            { id: 'manual'    as Protocol, icon: Globe2,  label: 'URL Manual', badge: 'Avançado',    desc: 'Informe a URL RTSP/RTMP diretamente.' },
          ] as const).map(({ id, icon: Icon, label, badge, desc }) => (
            <button
              key={id}
              onClick={() => setProtocol(id)}
              className="w-full text-left flex items-center gap-3 px-4 py-3 rounded-lg border transition-colors"
              style={protocol === id
                ? { borderColor: 'var(--accent)', background: 'var(--surface)' }
                : { borderColor: 'var(--border)', background: 'transparent' }}
            >
              <Icon size={16} style={protocol === id ? { color: 'var(--accent)' } : { color: 'var(--t3)' }} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-t1">{label}</span>
                  <span className="text-[10px] text-t3">{badge}</span>
                </div>
                <p className="text-xs text-t3 mt-0.5">{desc}</p>
              </div>
              <div className="w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0"
                style={{ borderColor: protocol === id ? 'var(--accent)' : 'var(--border)' }}>
                {protocol === id && <div className="w-2 h-2 rounded-full" style={{ background: 'var(--accent)' }} />}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* ── Step 1: Conexão ── */}
      {!done && step === 1 && (
        <div className="space-y-4">
          {protocol === 'rtmp_push' && (
            <div className="rounded-lg p-4 text-sm text-t2 space-y-1" style={{ background: 'var(--elevated)' }}>
              <p className="font-medium text-t1">Stream via RTMP Push</p>
              <p className="text-xs text-t3">Após criar a câmera, você receberá a URL e Stream Key para configurar no equipamento.</p>
            </div>
          )}

          {protocol === 'onvif' && (
            <div className="space-y-3">
              {/* Network scan */}
              <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
                <button
                  type="button"
                  className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-medium text-t2 hover:text-t1 transition"
                  style={{ background: 'var(--elevated)' }}
                  onClick={() => { setScanOpen((v) => !v); setDiscovered([]) }}
                >
                  <span className="flex items-center gap-2">
                    <Radio size={13} style={{ color: 'var(--accent)' }} />
                    Descobrir câmeras na rede
                  </span>
                  {scanOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
                {scanOpen && (
                  <div className="p-3 space-y-2 border-t" style={{ borderColor: 'var(--border)' }}>
                    <div className="flex gap-2">
                      <input
                        className="input flex-1 text-xs font-mono"
                        placeholder="192.168.1.0/24  (vazio = broadcast)"
                        value={scanSubnet}
                        onChange={(e) => setScanSubnet(e.target.value)}
                      />
                      <button
                        className="btn btn-ghost text-xs shrink-0"
                        onClick={handleScan}
                        disabled={scanning}
                      >
                        {scanning ? <Spinner size="sm" /> : <><Search size={13} className="mr-1" />Escanear</>}
                      </button>
                    </div>
                    {discovered.length > 0 && (
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {discovered.map((cam, i) => (
                          <button
                            key={i}
                            type="button"
                            className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-xs hover:bg-elevated transition"
                            style={{ border: '1px solid var(--border)' }}
                            onClick={() => pickDiscovered(cam)}
                          >
                            <CheckCircle2 size={12} style={{ color: 'var(--accent)' }} className="shrink-0" />
                            <div className="flex-1 min-w-0">
                              <span className="font-medium text-t1">{cam.ip}</span>
                              {(cam.manufacturer || cam.model) && (
                                <span className="text-t3 ml-1.5">{[cam.manufacturer, cam.model].filter(Boolean).join(' ')}</span>
                              )}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                    {!scanning && discovered.length === 0 && scanSubnet !== '' && (
                      <p className="text-xs text-t3 text-center py-1">Nenhuma câmera encontrada</p>
                    )}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2">
                  <label className="label">IP da câmera</label>
                  <input className="input" placeholder="192.168.1.100" value={form.onvif_ip} autoFocus
                    onChange={(e) => f('onvif_ip', e.target.value.replace(/[^0-9.]/g, ''))} />
                </div>
                <div>
                  <label className="label">Porta</label>
                  <input className="input" placeholder="80" value={form.onvif_port}
                    onChange={(e) => f('onvif_port', e.target.value.replace(/\D/g, ''))} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="label">Usuário</label>
                  <input className="input" value={form.onvif_username} onChange={(e) => f('onvif_username', e.target.value)} />
                </div>
                <div>
                  <label className="label">Senha</label>
                  <input className="input" type="password" placeholder="••••••••" value={form.onvif_password}
                    onChange={(e) => f('onvif_password', e.target.value)} />
                </div>
              </div>
              <button
                className="btn btn-ghost w-full text-sm"
                onClick={() => testOnvif(`http://${form.onvif_ip}:${form.onvif_port}/onvif/device_service`, form.onvif_username, form.onvif_password)}
                disabled={!form.onvif_ip || !form.onvif_password || connTest.status === 'loading'}
              >
                {connTest.status === 'loading' ? <Spinner size="sm" /> : <><Search size={14} className="mr-1" />Descobrir câmera</>}
              </button>
              {connTest.status === 'ok' && (
                <div className="space-y-2">
                  <p className="text-xs text-t2 flex items-center gap-1.5">
                    <CheckCircle2 size={12} style={{ color: 'var(--success)' }} />
                    {connTest.manufacturer}{connTest.model && ` — ${connTest.model}`}
                  </p>
                  {connTest.snapshot_url && (
                    <div className="rounded-lg overflow-hidden aspect-video" style={{ background: 'var(--elevated)' }}>
                      <img src={connTest.snapshot_url} alt="Preview ONVIF" className="w-full h-full object-cover" />
                    </div>
                  )}
                </div>
              )}
              {connTest.status === 'error' && (
                <p className="text-xs flex items-center gap-1.5" style={{ color: 'var(--danger)' }}>
                  <AlertTriangle size={12} />{connTest.error}
                </p>
              )}
            </div>
          )}

          {protocol === 'manual' && (
            <div className="space-y-2">
              <div>
                <label className="label">URL do stream</label>
                <input
                  className="input font-mono text-sm" autoFocus
                  placeholder="rtsp://admin:senha@192.168.1.100:554/stream"
                  value={form.manual_url}
                  onChange={(e) => f('manual_url', e.target.value.split(/[\n\r\s]+/).find((s) => s.length > 0) ?? e.target.value)}
                />
                {form.manual_url && !/^(rtsp|rtmp|http|https):\/\/.+/.test(form.manual_url) && (
                  <p className="text-xs mt-1 flex items-center gap-1" style={{ color: 'var(--danger)' }}>
                    <AlertTriangle size={11} />Use rtsp:// ou rtmp://
                  </p>
                )}
              </div>
              <button onClick={() => setHelpOpen((v) => !v)} className="flex items-center gap-1 text-xs text-t3 hover:text-t2">
                {helpOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                Como encontrar a URL da minha câmera?
              </button>
              {helpOpen && (
                <div className="rounded-lg p-3 text-xs text-t3 space-y-1.5" style={{ background: 'var(--elevated)' }}>
                  <p><strong className="text-t2">Hikvision:</strong> <code>rtsp://admin:senha@IP:554/Streaming/Channels/101</code></p>
                  <p><strong className="text-t2">Intelbras:</strong> <code>rtsp://admin:senha@IP:554/cam/realmonitor?channel=1&subtype=0</code></p>
                  <p><strong className="text-t2">Dahua:</strong> <code>rtsp://admin:senha@IP:554/cam/realmonitor?channel=1&subtype=0</code></p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Step 2: Detalhes ── */}
      {!done && step === 2 && (
        <div className="space-y-4">
          <div>
            <label className="label">Nome da câmera</label>
            <input className="input" autoFocus maxLength={100} placeholder="Ex: Portaria Principal"
              value={form.name} onChange={(e) => f('name', e.target.value)} />
            {form.name.trim().length > 0 && form.name.trim().length < 2 && (
              <p className="text-xs mt-1" style={{ color: 'var(--danger)' }}>Mínimo 2 caracteres</p>
            )}
          </div>

          <div>
            <label className="label">Localização <span className="text-t3/50">(opcional)</span></label>
            <input className="input" maxLength={200} placeholder="Ex: Bloco A — Andar 2"
              value={form.location} onChange={(e) => f('location', e.target.value)} />
          </div>

          <div>
            <label className="label">Fabricante</label>
            <div className="flex gap-2">
              {['generic', 'hikvision', 'intelbras'].map((m) => (
                <button key={m} onClick={() => f('manufacturer', m)}
                  className="flex-1 py-2 rounded-lg border text-sm transition-colors capitalize"
                  style={form.manufacturer === m
                    ? { borderColor: 'var(--accent)', color: 'var(--accent)', background: 'var(--surface)' }
                    : { borderColor: 'var(--border)', color: 'var(--t3)' }}>
                  {m === 'generic' ? 'Genérico' : m.charAt(0).toUpperCase() + m.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="label">Retenção de gravações</label>
            <div className="flex gap-2">
              {RETENTION_OPTIONS.map(({ days, label }) => (
                <button key={days} onClick={() => f('retention_days', days)}
                  className="flex-1 py-2 rounded-lg border text-sm transition-colors"
                  style={form.retention_days === days
                    ? { borderColor: 'var(--accent)', color: 'var(--accent)', background: 'var(--surface)' }
                    : { borderColor: 'var(--border)', color: 'var(--t3)' }}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Feature toggles */}
          <div className="space-y-2">
            <p className="text-[11px] font-medium text-t3 uppercase tracking-wider">Funcionalidades</p>
            {([
              { key: 'ia_enabled',    Icon: Cpu,  label: 'Analytics / IA', desc: 'Habilita análise de vídeo por IA nesta câmera' },
              { key: 'ptz_supported', Icon: Move, label: 'PTZ',            desc: 'Câmera suporta Pan-Tilt-Zoom' },
            ] as const).map(({ key, Icon, label, desc }) => (
              <div key={key}
                className="flex items-center justify-between px-3 py-2.5 rounded-lg border"
                style={{ borderColor: 'var(--border)', background: 'var(--elevated)' }}
              >
                <div className="flex items-center gap-2.5">
                  <Icon size={14} className="text-t3 shrink-0" />
                  <div>
                    <p className="text-sm text-t1">{label}</p>
                    <p className="text-xs text-t3">{desc}</p>
                  </div>
                </div>
                <Toggle
                  checked={form[key] as boolean}
                  onChange={(v) => f(key, v)}
                />
              </div>
            ))}
          </div>

          {/* GPS — collapsible */}
          <div>
            <button
              onClick={() => setGpsOpen((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-t3 hover:text-t2 transition-colors"
            >
              <MapPin size={12} />
              Coordenadas GPS
              {gpsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              <span className="text-t3/50 ml-0.5">(opcional)</span>
            </button>
            {gpsOpen && (
              <div className="grid grid-cols-2 gap-2 mt-2">
                <div>
                  <label className="label">Latitude</label>
                  <input className="input font-mono text-sm" placeholder="-23.5505"
                    value={form.latitude}
                    onChange={(e) => f('latitude', e.target.value.replace(/[^0-9.\-]/g, ''))} />
                </div>
                <div>
                  <label className="label">Longitude</label>
                  <input className="input font-mono text-sm" placeholder="-46.6333"
                    value={form.longitude}
                    onChange={(e) => f('longitude', e.target.value.replace(/[^0-9.\-]/g, ''))} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Step 3: Qualidade ── */}
      {!done && step === 3 && (
        <div className="space-y-2">
          <p className="text-xs text-t3 mb-3">Resolução de gravação e consumo estimado de armazenamento.</p>
          {QUALITY_OPTIONS.map((q) => (
            <button key={q.value} onClick={() => f('stream_quality', q.value)}
              className="w-full flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-colors"
              style={form.stream_quality === q.value
                ? { borderColor: 'var(--accent)', background: 'var(--surface)' }
                : { borderColor: 'var(--border)' }}>
              <div>
                <span className="text-sm font-medium text-t1">{q.label}</span>
                <p className="text-xs text-t3 mt-0.5">{q.sub}</p>
              </div>
              <div className="w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0"
                style={{ borderColor: form.stream_quality === q.value ? 'var(--accent)' : 'var(--border)' }}>
                {form.stream_quality === q.value && <div className="w-2 h-2 rounded-full" style={{ background: 'var(--accent)' }} />}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* ── Step 4: Revisão ── */}
      {!done && step === 4 && (
        <div className="space-y-1">
          <p className="text-xs text-t3 mb-3">Confirme os dados antes de criar.</p>
          {([
            ['Método',     { rtmp_push: 'RTMP Push', onvif: 'ONVIF', manual: 'URL Manual' }[protocol]],
            ['Nome',       form.name],
            ['Localização', form.location || '—'],
            ['Fabricante', form.manufacturer === 'generic' ? 'Genérico' : form.manufacturer],
            ['Qualidade',  QUALITY_OPTIONS.find((q) => q.value === form.stream_quality)?.label],
            ['Retenção',   `${form.retention_days} dias`],
            ['Analytics',  form.ia_enabled    ? 'Habilitado' : 'Desabilitado'],
            ['PTZ',        form.ptz_supported ? 'Habilitado' : 'Desabilitado'],
            ...(form.latitude && form.longitude
              ? [['GPS', `${form.latitude}, ${form.longitude}`]]
              : []),
          ] as [string, string][]).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between py-2.5 border-b" style={{ borderColor: 'var(--border)' }}>
              <span className="text-xs text-t3">{k}</span>
              <span className="text-sm text-t1 font-medium">{v}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── Done ── */}
      {done && (
        <div className="space-y-4">
          {/* Thumbnail preview */}
          {protocol !== 'rtmp_push' && (
            <div
              className="rounded-lg overflow-hidden w-full"
              style={{ background: 'var(--elevated)', aspectRatio: '16/9' }}
            >
              {snapshotLoading ? (
                <div className="w-full h-full flex items-center justify-center">
                  <Spinner size="sm" />
                </div>
              ) : done.snapshot_url ? (
                <img src={done.snapshot_url} alt="Preview" className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-t3">
                  <VideoOff size={22} />
                  <p className="text-xs">Aguardando primeiro frame</p>
                </div>
              )}
            </div>
          )}

          <p className="text-sm text-t2">
            {protocol === 'rtmp_push'
              ? 'Configure as informações abaixo na câmera para iniciar o stream.'
              : 'O stream estará disponível assim que a câmera enviar dados.'}
          </p>

          {protocol === 'rtmp_push' && done.rtmp_url && (
            <div className="space-y-3">
              <div>
                <label className="label">URL RTMP</label>
                <div className="flex items-center gap-2 mt-1">
                  <code className="flex-1 text-xs font-mono rounded-lg px-3 py-2 text-t1 break-all" style={{ background: 'var(--elevated)' }}>
                    {done.rtmp_url}
                  </code>
                  <button className="btn btn-ghost w-8 h-8 p-0 shrink-0" onClick={() => copy(done.rtmp_url!, 'url')}>
                    {copied === 'url' ? <Check size={13} style={{ color: 'var(--success)' }} /> : <Copy size={13} />}
                  </button>
                </div>
              </div>
              {done.stream_key && (
                <div>
                  <label className="label">Stream Key</label>
                  <div className="flex items-center gap-2 mt-1">
                    <code className="flex-1 text-xs font-mono rounded-lg px-3 py-2 text-t1" style={{ background: 'var(--elevated)' }}>
                      {done.stream_key}
                    </code>
                    <button className="btn btn-ghost w-8 h-8 p-0 shrink-0" onClick={() => copy(done.stream_key!, 'key')}>
                      {copied === 'key' ? <Check size={13} style={{ color: 'var(--success)' }} /> : <Copy size={13} />}
                    </button>
                  </div>
                </div>
              )}
              <p className="text-xs text-t3 flex items-center gap-1.5">
                <AlertTriangle size={11} style={{ color: 'var(--warning)' }} />
                A Stream Key não será exibida novamente.
              </p>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
