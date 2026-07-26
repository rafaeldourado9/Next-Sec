import { useEffect, useState, useCallback } from 'react'
import { Database, Wifi, Radio, Server, Cpu, HardDrive, AlertTriangle, CheckCircle, XCircle, RefreshCw } from 'lucide-react'
import { format } from 'date-fns'
import { healthService, type HealthStatus, type Metrics } from '@/services/health'
import { PageSpinner } from '@/components/ui/Spinner'

const SERVICE_ICONS: Record<string, React.ElementType> = {
  db: Database,
  redis: Radio,
  rabbitmq: Wifi,
  mediamtx: Server,
  analytics: Cpu,
}

const SERVICE_LABELS: Record<string, string> = {
  db: 'Banco de Dados',
  redis: 'Redis',
  rabbitmq: 'RabbitMQ',
  mediamtx: 'MediaMTX',
  analytics: 'Analytics Service',
}

function ServiceStatusCard({ name, status }: { name: string; status: string }) {
  const Icon = SERVICE_ICONS[name] ?? Server
  const isOk = status === 'ok'
  const isDegraded = status === 'degraded'
  const color = isOk ? '#22c55e' : isDegraded ? '#f59e0b' : '#ef4444'
  const label = isOk ? 'Online' : isDegraded ? 'Degradado' : 'Offline'

  return (
    <div className="card p-4 flex items-center gap-3">
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: `${color}18` }}
      >
        <Icon size={20} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-t1">{SERVICE_LABELS[name] ?? name}</p>
        <p className="text-xs tabular-nums" style={{ color }}>
          {label}
        </p>
        {status !== 'ok' && status !== 'degraded' && (
          <p className="text-xs text-t3 truncate mt-0.5" title={status}>
            {status.slice(0, 60)}...
          </p>
        )}
      </div>
      {isOk
        ? <CheckCircle size={16} className="text-green-500 shrink-0" />
        : isDegraded
          ? <AlertTriangle size={16} className="text-yellow-500 shrink-0" />
          : <XCircle size={16} className="text-red-500 shrink-0" />
      }
    </div>
  )
}

export function SystemHealthPage() {
  const [health, setHealth]     = useState<HealthStatus | null>(null)
  const [metrics, setMetrics]   = useState<Metrics | null>(null)
  const [loading, setLoading]   = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())

  const loadData = useCallback(() => {
    setLoading(true)
    Promise.all([
      healthService.check(),
      healthService.metrics(),
    ])
      .then(([h, m]) => {
        setHealth(h)
        setMetrics(m)
        setLastUpdate(new Date())
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadData() }, [loadData])

  // Auto-refresh a cada 30s
  useEffect(() => {
    const interval = setInterval(loadData, 30000)
    return () => clearInterval(interval)
  }, [loadData])

  if (loading && !health) return <PageSpinner />

  if (!health || !metrics) {
    return <div className="py-16 text-center text-sm text-t3">Não foi possível carregar informações de saúde do sistema.</div>
  }

  const uptimePct = metrics.cameras_total > 0
    ? Math.round((metrics.cameras_online / metrics.cameras_total) * 100)
    : 0

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-t1">Saúde do Sistema</p>
          <p className="text-xs text-t3 mt-0.5">
            Última verificação: {format(lastUpdate, 'HH:mm:ss')} · Auto-refresh 30s
          </p>
        </div>
        <button className="btn btn-ghost gap-1.5 text-xs" onClick={loadData}>
          <RefreshCw size={14} /> Atualizar
        </button>
      </div>

      {/* Overall status banner */}
      <div
        className="card p-4 flex items-center gap-3"
        style={{
          background: health.status === 'healthy' ? '#22c55e0d' : '#ef44440d',
          borderColor: health.status === 'healthy' ? '#22c55e30' : '#ef444430',
        }}
      >
        {health.status === 'healthy'
          ? <CheckCircle size={22} className="text-green-500" />
          : <AlertTriangle size={22} className="text-red-500" />
        }
        <div>
          <p className="text-sm font-semibold text-t1">
            {health.status === 'healthy' ? 'Todos os serviços operacionais' : 'Um ou mais serviços com problemas'}
          </p>
          <p className="text-xs text-t3">
            {metrics.cameras_online} de {metrics.cameras_total} câmeras online ({uptimePct}%)
          </p>
        </div>
      </div>

      {/* Service cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        {Object.entries(health.services).map(([name, status]) => (
          <ServiceStatusCard key={name} name={name} status={status} />
        ))}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { icon: Server, label: 'Tenants', value: metrics.tenants.toString(), color: '#3b82f6' },
          { icon: Cpu, label: 'Usuários', value: metrics.users.toString(), color: '#8b5cf6' },
          { icon: HardDrive, label: 'Eventos', value: metrics.events_total.toLocaleString('pt-BR'), color: '#f59e0b' },
          { icon: Wifi, label: 'Streams Ativos', value: metrics.active_streams.toString(), color: '#22c55e' },
        ].map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="card px-4 py-3">
            <div className="flex items-center gap-2 mb-2">
              <Icon size={15} style={{ color }} />
              <p className="text-xs text-t3">{label}</p>
            </div>
            <p className="text-2xl font-bold text-t1 tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      {/* Camera uptime */}
      <div className="card p-4">
        <p className="text-sm font-semibold text-t1 mb-3">Uptime de Câmeras</p>
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-t2">Câmeras online</span>
            <span className="text-t1 font-bold tabular-nums">
              {metrics.cameras_online} / {metrics.cameras_total}
            </span>
          </div>
          <div className="h-3 rounded-full overflow-hidden" style={{ background: 'var(--elevated)' }}>
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${uptimePct}%`,
                background: uptimePct >= 90 ? '#22c55e' : uptimePct >= 70 ? '#f59e0b' : '#ef4444',
              }}
            />
          </div>
          <p className="text-xs text-t3 text-right">{uptimePct}% online</p>
        </div>
      </div>

      {/* Version info */}
      <div className="card p-3 flex items-center justify-between text-xs">
        <span className="text-t3">Versão da API</span>
        <code className="text-t2 bg-elevated px-2 py-0.5 rounded">{health.version}</code>
      </div>
    </div>
  )
}
