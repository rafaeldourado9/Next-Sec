import { useLocation } from 'react-router-dom'
import { Bell, Menu, User } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { useSSE } from '@/hooks/useSSE'
import { clsx } from 'clsx'

const TITLES: Record<string, string> = {
  '/dashboard':     'Dashboard',
  '/cameras':       'Câmeras',
  '/detections':    'Detecções ALPR',
  '/events':        'Eventos',
  '/analytics':     'Dashboard Analytics',
  '/reports':       'Relatórios',
  '/audit':         'Auditoria',
  '/lgpd':          'LGPD',
  '/notifications': 'Notificações',
  '/agents':        'Agentes',
  '/users':         'Usuários',
  '/settings':      'Configurações',
}

interface HeaderProps {
  onMenuClick?: () => void
}

export function Header({ onMenuClick }: HeaderProps) {
  const { pathname } = useLocation()
  const user = useAuthStore((s) => s.user)
  const { connected } = useSSE()

  const title = Object.entries(TITLES)
    .sort((a, b) => b[0].length - a[0].length)
    .find(([key]) => pathname.startsWith(key))?.[1] ?? 'VMS'

  return (
    <header
      className="h-14 flex items-center justify-between px-4 shrink-0 border-b"
      style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
    >
      <div className="flex items-center gap-3">
        {/* Hamburger — only on mobile */}
        <button
          className="md:hidden btn btn-ghost w-8 h-8 p-0 rounded-lg"
          onClick={onMenuClick}
          aria-label="Menu"
        >
          <Menu size={18} />
        </button>
        <h1 className="text-sm font-semibold text-t1">{title}</h1>
      </div>

      <div className="flex items-center gap-2">
        {/* SSE status */}
        <div
          title={connected ? 'Tempo real ativo' : 'Desconectado do tempo real'}
          className={clsx(
            'w-2 h-2 rounded-full transition-colors',
            connected ? 'bg-green-500' : 'bg-zinc-600',
          )}
        />

        <button className="btn btn-ghost w-8 h-8 p-0 rounded-lg relative">
          <Bell size={16} />
        </button>

        <div
          className="flex items-center gap-2 pl-2 border-l"
          style={{ borderColor: 'var(--border)' }}
        >
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-semibold"
            style={{ background: 'var(--accent)' }}
          >
            {user?.full_name?.charAt(0).toUpperCase() ?? <User size={14} />}
          </div>
          {user && (
            <div className="hidden sm:block">
              <p className="text-xs font-medium text-t1 leading-none">{user.full_name}</p>
              <p className="text-xs text-t3 leading-none mt-0.5">{user.role}</p>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
