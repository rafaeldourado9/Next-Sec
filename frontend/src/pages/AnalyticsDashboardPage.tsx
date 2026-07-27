import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bell, AlertTriangle, Info, TrendingUp, Camera, Brain,
  Activity, BarChart3, Clock, Eye,
} from 'lucide-react'
import { format } from 'date-fns'
import { clsx } from 'clsx'
import toast from 'react-hot-toast'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, AreaChart, Area,
} from 'recharts'
import { analyticsService, type AnalyticsStats, type AnalyticsEvent } from '@/services/analytics'
import { useSSE } from '@/hooks/useSSE'
import { PageSpinner } from '@/components/ui/Spinner'
import { Badge } from '@/components/ui/Badge'

const SEVERITY_CONFIG: Record<string, { color: string; icon: React.ElementType; label: string; bg: string }> = {
  critical: { color: '#ef4444', icon: AlertTriangle, label: 'Críticos', bg: 'rgba(239,68,68,0.1)' },
  warning:  { color: '#f59e0b', icon: Bell,         label: 'Alertas',  bg: 'rgba(245,158,11,0.1)' },
  info:     { color: '#3b82f6', icon: Info,         label: 'Info',     bg: 'rgba(59,130,246,0.1)' },
}

const PLUGIN_CONFIG: Record<string, { color: string; label: string }> = {
  intrusion:    { color: '#ef4444', label: 'Cerca Virtual' },
  people_count: { color: '#3b82f6', label: 'Contagem de Pessoas' },
}

const PERIODS = [
  { label: '1h',  value: 1 },
  { label: '6h',  value: 6 },
  { label: '24h', value: 24 },
  { label: '7d',  value: 168 },
  { label: '30d', value: 720 },
]

const COLORS = ['#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6', '#22c55e', '#ec4899', '#14b8a6', '#f97316', '#6366f1']

function StatCard({
  label, value, icon: Icon, color, bg, subtitle,
}: {
  label: string
  value: string
  icon: React.ElementType
  color: string
  bg: string
  subtitle?: string
}) {
  return (
    <div
      className="rounded-xl p-4 transition-all hover:scale-[1.01]"
      style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
    >
      <div className="flex items-center gap-2 mb-3">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: bg }}
        >
          <Icon size={16} style={{ color }} />
        </div>
        <p className="text-xs text-t3">{label}</p>
      </div>
      <p className="text-2xl font-bold text-t1 tabular-nums">{value}</p>
      {subtitle && <p className="text-[10px] text-t3 mt-1">{subtitle}</p>}
    </div>
  )
}

interface TooltipPayloadEntry {
  name: string
  value: number | string
  color: string
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TooltipPayloadEntry[]
  label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div
      className="rounded-lg px-3 py-2 text-xs"
      style={{
        background: 'rgba(10,10,16,0.95)',
        border: '1px solid rgba(255,255,255,0.1)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <p className="text-t3 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-t1 font-medium" style={{ color: p.color }}>
          {p.name}: {p.value}
        </p>
      ))}
    </div>
  )
}

export function AnalyticsDashboardPage() {
  const navigate = useNavigate()
  const [stats, setStats]           = useState<AnalyticsStats | null>(null)
  const [events, setEvents]         = useState<AnalyticsEvent[]>([])
  const [loading, setLoading]       = useState(true)
  const [selectedPeriod, setSelectedPeriod] = useState(24)
  const [selectedSeverity, setSelectedSeverity] = useState<string | null>(null)

  const loadData = useCallback((hours: number) => {
    setLoading(true)
    Promise.all([
      analyticsService.getStats(hours),
      analyticsService.getEvents({
        limit: 100,
        occurred_after: new Date(Date.now() - hours * 3600_000).toISOString(),
      }),
    ])
      .then(([s, e]) => { setStats(s); setEvents(e) })
      .catch(() => { toast.error('Erro ao carregar dados de analytics') })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadData(selectedPeriod) }, [selectedPeriod, loadData])

  // Real-time: recarrega o dashboard quando um evento analítico novo chega.
  const { lastEvent } = useSSE()
  const lastSeenRef = useRef<unknown>(null)
  useEffect(() => {
    if (!lastEvent || lastEvent === lastSeenRef.current) return
    lastSeenRef.current = lastEvent
    const inner = (lastEvent as { data?: { event_type?: string } }).data
    if (!inner?.event_type?.startsWith('analytics.')) return
    loadData(selectedPeriod)
  }, [lastEvent, selectedPeriod, loadData])

  // Hourly area chart data
  const hourlyData = useMemo(() => {
    const hours: Record<string, number> = {}
    const cutoff = Date.now() - selectedPeriod * 3600_000
    events.forEach(ev => {
      const t = new Date(ev.occurred_at).getTime()
      if (t < cutoff) return
      const hourKey = format(new Date(t), 'HH:00')
      hours[hourKey] = (hours[hourKey] || 0) + 1
    })

    const result: { label: string; value: number }[] = []
    const now = new Date()
    const step = selectedPeriod <= 24 ? 1 : Math.ceil(selectedPeriod / 24)
    for (let i = Math.min(selectedPeriod, 24); i >= 0; i -= step) {
      const h = new Date(now.getTime() - i * 3600_000)
      const key = format(h, 'HH:00')
      result.push({ label: key, value: hours[key] || 0 })
    }
    return result
  }, [events, selectedPeriod])

  // Plugin bar data
  const pluginData = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.by_plugin).map(([plugin, count], i) => ({
      name: PLUGIN_CONFIG[plugin]?.label || plugin,
      value: count,
      color: PLUGIN_CONFIG[plugin]?.color || COLORS[i % COLORS.length],
    })).sort((a, b) => b.value - a.value)
  }, [stats])

  // Severity pie data
  const severityData = useMemo(() => {
    if (!stats) return []
    return Object.entries(stats.by_severity).map(([severity, count]) => ({
      name: SEVERITY_CONFIG[severity]?.label || severity,
      value: count,
      color: SEVERITY_CONFIG[severity]?.color || '#888',
    }))
  }, [stats])

  // Camera bar data
  const cameraData = useMemo(() => {
    if (!stats) return []
    return stats.top_cameras.map((cam, i) => ({
      name: cam.camera_name || cam.camera_id?.slice(0, 8) || `Cam ${i + 1}`,
      value: cam.count,
    })).slice(0, 8)
  }, [stats])

  // Filtered events
  const filteredEvents = useMemo(() => {
    if (!selectedSeverity) return events
    return events.filter(e => e.severity === selectedSeverity)
  }, [events, selectedSeverity])

  if (loading && !stats) return <PageSpinner />

  const total = stats?.total ?? 0
  const critical = stats?.by_severity?.critical ?? 0
  const warning = stats?.by_severity?.warning ?? 0
  const info = stats?.by_severity?.info ?? 0

  const avgPerHour = selectedPeriod > 0 ? (total / selectedPeriod).toFixed(1) : '0'

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-accent" />
            <p className="text-sm font-semibold text-t1">Analytics Dashboard</p>
          </div>
          <p className="text-xs text-t3 mt-0.5">Eventos de IA e detecções em tempo real</p>
        </div>

        <div data-testid="period-selector" className="flex items-center gap-1 p-1 rounded-xl" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
          {PERIODS.map(p => (
            <button
              key={p.value}
              data-testid={`period-btn-${p.label}`}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition ${
                selectedPeriod === p.value
                  ? 'text-white'
                  : 'text-t3 hover:text-t2'
              }`}
              style={selectedPeriod === p.value ? { background: 'var(--accent)' } : {}}
              onClick={() => setSelectedPeriod(p.value)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div data-testid="stats-cards" className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Total de Eventos"
          value={total.toLocaleString('pt-BR')}
          icon={TrendingUp}
          color="#3b82f6"
          bg="rgba(59,130,246,0.1)"
          subtitle={`~${avgPerHour}/hora em média`}
        />
        <StatCard
          label="Críticos"
          value={critical.toString()}
          icon={AlertTriangle}
          color="#ef4444"
          bg="rgba(239,68,68,0.1)"
          subtitle={critical > 0 ? 'Requer atenção imediata' : 'Nenhum evento crítico'}
        />
        <StatCard
          label="Alertas"
          value={warning.toString()}
          icon={Bell}
          color="#f59e0b"
          bg="rgba(245,158,11,0.1)"
        />
        <StatCard
          label="Info"
          value={info.toString()}
          icon={Info}
          color="#3b82f6"
          bg="rgba(59,130,246,0.1)"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Hourly trend */}
        <div
          className="rounded-xl p-4 lg:col-span-2"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 size={16} className="text-t2" />
            <p className="text-sm font-semibold text-t1">Tendência Horária</p>
          </div>
          {hourlyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={hourlyData}>
                <defs>
                  <linearGradient id="colorEvents" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="label" tick={{ fill: '#71717a', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#71717a', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="value" name="Eventos" stroke="#3b82f6" fillOpacity={1} fill="url(#colorEvents)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[220px] text-t3 text-xs">
              Sem dados para o período selecionado
            </div>
          )}
        </div>

        {/* Severity distribution */}
        <div
          className="rounded-xl p-4"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Eye size={16} className="text-t2" />
            <p className="text-sm font-semibold text-t1">Severidade</p>
          </div>
          {severityData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={severityData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={4}
                  dataKey="value"
                >
                  {severityData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[220px] text-t3 text-xs">
              Sem dados de severidade
            </div>
          )}
          <div className="flex justify-center gap-3 mt-2">
            {severityData.map((s) => (
              <div key={s.name} className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full" style={{ background: s.color }} />
                <span className="text-[10px] text-t3">{s.name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Second charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* By plugin */}
        <div
          className="rounded-xl p-4"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Brain size={16} className="text-t2" />
            <p className="text-sm font-semibold text-t1">Por Plugin</p>
          </div>
          {pluginData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={pluginData} layout="vertical" margin={{ left: 20, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#71717a', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis dataKey="name" type="category" tick={{ fill: '#a1a1aa', fontSize: 10 }} axisLine={false} tickLine={false} width={120} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" name="Eventos" radius={[0, 4, 4, 0]}>
                  {pluginData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[250px] text-t3 text-xs">
              Sem dados de plugins
            </div>
          )}
        </div>

        {/* Top cameras */}
        <div
          className="rounded-xl p-4"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2 mb-4">
            <Camera size={16} className="text-t2" />
            <p className="text-sm font-semibold text-t1">Top Câmeras</p>
          </div>
          {cameraData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={cameraData} margin={{ left: 20, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: '#a1a1aa', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#71717a', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" name="Eventos" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[250px] text-t3 text-xs">
              Sem dados de câmeras
            </div>
          )}
        </div>
      </div>

      {/* Recent events */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
      >
        <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="flex items-center gap-2">
            <Clock size={14} className="text-t2" />
            <span className="text-sm font-semibold text-t1">Eventos Recentes</span>
            <span className="text-xs text-t3">({filteredEvents.length})</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              className={clsx('px-2 py-0.5 rounded text-[10px] font-medium transition', !selectedSeverity && 'text-accent bg-accent/10')}
              style={!selectedSeverity ? {} : { color: 'var(--text-3)' }}
              onClick={() => setSelectedSeverity(null)}
            >
              Todos
            </button>
            {(['critical', 'warning', 'info'] as const).map((sev) => (
              <button
                key={sev}
                className={clsx('px-2 py-0.5 rounded text-[10px] font-medium transition')}
                style={selectedSeverity === sev ? {
                  color: SEVERITY_CONFIG[sev].color,
                  background: SEVERITY_CONFIG[sev].bg,
                } : { color: 'var(--text-3)' }}
                onClick={() => setSelectedSeverity(selectedSeverity === sev ? null : sev)}
              >
                {SEVERITY_CONFIG[sev].label}
              </button>
            ))}
          </div>
        </div>

        {filteredEvents.length === 0 ? (
          <div className="py-16 text-center text-sm text-t3">Nenhum evento de analytics encontrado</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Hora', 'Câmera', 'Plugin', 'Tipo', 'Confiança', 'Severidade'].map(h => (
                    <th key={h} className="px-3 py-2.5 text-xs font-medium text-t3 whitespace-nowrap text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredEvents.slice(0, 30).map(ev => {
                  const sevCfg = SEVERITY_CONFIG[ev.severity] ?? SEVERITY_CONFIG.info
                  const SeverityIcon = sevCfg.icon
                  const pluginCfg = PLUGIN_CONFIG[ev.plugin_id]

                  return (
                    <tr
                      key={ev.id}
                      className="hover:bg-elevated transition cursor-pointer"
                      style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                      onClick={() => navigate(`/events?camera_id=${ev.camera_id}`)}
                    >
                      <td className="px-3 py-2.5 text-xs text-t3 whitespace-nowrap tabular-nums">
                        {format(new Date(ev.occurred_at), 'dd/MM HH:mm:ss')}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-t2 font-mono max-w-[120px] truncate">
                        {ev.camera_name ?? ev.camera_id?.slice(0, 8) ?? '—'}
                      </td>
                      <td className="px-3 py-2.5 text-xs">
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ background: pluginCfg?.color ?? '#888' }}
                          />
                          <span className="text-t2">{pluginCfg?.label || ev.plugin_id}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-t2">{ev.event_type}</td>
                      <td className="px-3 py-2.5 text-xs tabular-nums">
                        {ev.confidence !== null && ev.confidence !== undefined
                          ? `${Math.round(ev.confidence * 100)}%`
                          : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge variant={ev.severity === 'critical' ? 'danger' : ev.severity === 'warning' ? 'warning' : 'info'} dot>
                          <span className="flex items-center gap-1">
                            <SeverityIcon size={11} />
                            {sevCfg.label}
                          </span>
                        </Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
