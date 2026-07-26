import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'

const FULLSCREEN_ROUTES = ['/cameras']

export function Layout() {
  const { pathname } = useLocation()
  const fullscreen = FULLSCREEN_ROUTES.some((r) => pathname.startsWith(r))

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg)' }}>
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <main className={fullscreen ? 'flex-1 min-h-0 overflow-hidden' : 'flex-1 overflow-auto p-4'}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
