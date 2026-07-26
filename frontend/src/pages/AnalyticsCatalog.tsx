import { useEffect, useState } from 'react'
import {
  ShieldAlert, Users, BarChart3, ChevronRight, Activity, Cpu, Brain,
} from 'lucide-react'
import { clsx } from 'clsx'
import { Link } from 'react-router-dom'
import { analyticsService, type AnalyticsCatalogItem, type AnalyticsStats } from '@/services/analytics'

const PLUGIN_ICONS: Record<string, React.ElementType> = {
  intrusion:    ShieldAlert,
  people_count: Users,
}

const CATEGORY_FILTERS = [
  { id: 'all', label: 'Todos' },
  { id: 'security', label: 'Patrimonial' },
  { id: 'traffic', label: 'Tráfego' },
] as const

export function AnalyticsCatalog() {
  const [plugins, setPlugins]         = useState<AnalyticsCatalogItem[]>([])
  const [stats, setStats]             = useState<AnalyticsStats | null>(null)
  const [category, setCategory]       = useState('all')
  const [loading, setLoading]         = useState(true)

  useEffect(() => {
    Promise.all([
      analyticsService.getCatalog(),
      analyticsService.getStats(24),
    ])
      .then(([cat, st]) => { setPlugins(cat); setStats(st) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = category === 'all' ? plugins : plugins.filter(p => p.category === category)

  return (
    <div className="p-6 space-y-6 overflow-y-auto">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <Brain size={22} className="text-accent" />
          <h1 className="text-xl font-bold text-t1">Analytics de Vídeo</h1>
        </div>
        <p className="text-sm text-t3">
          Plugins de IA rodando no servidor. Detecções em tempo real via stream RTSP.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          icon={Activity}
          label="Eventos (24h)"
          value={stats?.total ?? '—'}
          color="text-accent"
        />
        <StatCard
          icon={ShieldAlert}
          label="Críticos"
          value={stats?.by_severity?.critical ?? 0}
          color="text-red-500"
        />
        <StatCard
          icon={Brain}
          label="Plugins ativos"
          value={plugins.filter(p => p.is_available).length}
          color="text-green-500"
        />
        <StatCard
          icon={BarChart3}
          label="Modelos"
          value={plugins.length}
          color="text-blue-500"
        />
      </div>

      {/* Quick link to events */}
      <Link
        to="/analytics/events"
        className="flex items-center justify-between px-4 py-3 rounded-xl border transition hover:border-accent/50"
        style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-3">
          <ShieldAlert size={18} className="text-accent" />
          <div>
            <p className="text-sm font-medium text-t1">Ver Detecções</p>
            <p className="text-xs text-t3">Eventos gerados pelos plugins em tempo real</p>
          </div>
        </div>
        <ChevronRight size={16} className="text-t3" />
      </Link>

      {/* Category filter */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {CATEGORY_FILTERS.map(f => (
          <button
            key={f.id}
            onClick={() => setCategory(f.id)}
            className={clsx(
              'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all',
              category === f.id
                ? 'text-white'
                : 'text-t2 hover:text-t1',
            )}
            style={{
              background: category === f.id ? 'var(--accent)' : 'var(--elevated)',
              border: '1px solid var(--border)',
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Plugin grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="h-48 rounded-xl animate-pulse"
              style={{ background: 'var(--elevated)' }}
            />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map(plugin => (
            <PluginCard key={plugin.id} plugin={plugin} eventCount={stats?.by_plugin?.[plugin.id] ?? 0} />
          ))}
          {filtered.length === 0 && (
            <p className="col-span-full text-center text-sm text-t3 py-12">
              Nenhum plugin nesta categoria.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function StatCard({
  icon: Icon, label, value, color,
}: {
  icon: React.ElementType
  label: string
  value: number | string
  color: string
}) {
  return (
    <div
      className="rounded-xl p-4 border"
      style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon size={15} className={color} />
        <p className="text-xs text-t3">{label}</p>
      </div>
      <p className="text-2xl font-bold text-t1 tabular-nums">{value}</p>
    </div>
  )
}

function PluginCard({ plugin, eventCount }: { plugin: AnalyticsCatalogItem; eventCount: number }) {
  const Icon = PLUGIN_ICONS[plugin.id] ?? Brain

  return (
    <div
      className="rounded-xl border p-4 flex flex-col gap-3 hover:border-accent/40 transition-all"
      style={{ background: 'var(--elevated)', borderColor: 'var(--border)' }}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2.5">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: 'var(--surface)' }}
          >
            <Icon size={18} className="text-accent" />
          </div>
          <div>
            <p className="text-sm font-semibold text-t1 leading-tight">{plugin.name}</p>
            <p className="text-[10px] text-t3">v{plugin.version}</p>
          </div>
        </div>
        <span
          className="px-2 py-0.5 rounded text-[10px] font-medium text-green-400"
          style={{ background: 'rgba(34,197,94,0.1)' }}
        >
          Ativo
        </span>
      </div>

      <p className="text-xs text-t2 line-clamp-2 flex-1">{plugin.description}</p>

      <div className="flex flex-wrap gap-1">
        {plugin.classes.map(cls => (
          <span
            key={cls}
            className="px-1.5 py-0.5 rounded text-[10px] text-t3"
            style={{ background: 'var(--surface)' }}
          >
            {cls}
          </span>
        ))}
      </div>

      <div
        className="flex items-center justify-between pt-2 border-t text-[10px] text-t3"
        style={{ borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Cpu size={10} />
            {plugin.model_size}
          </span>
          <span className="flex items-center gap-1">
            <Activity size={10} />
            {plugin.fps_cost} fps/cam
          </span>
        </div>
        {eventCount > 0 && (
          <Link to="/analytics/events" className="text-accent hover:underline">
            {eventCount} eventos
          </Link>
        )}
      </div>
    </div>
  )
}
