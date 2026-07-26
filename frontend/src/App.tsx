import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { Layout } from '@/components/layout/Layout'
import { useAuthStore } from '@/store/authStore'
import { LicenseGate } from '@/components/license/LicenseGate'

import { LoginPage }           from '@/pages/LoginPage'
import { DashboardPage }       from '@/pages/DashboardPage'
import { CamerasPage }         from '@/pages/CamerasPage'
import { CameraDetailPage }    from '@/pages/CameraDetailPage'
import { ContactsPage }        from '@/pages/ContactsPage'
import { NotificationsPage }   from '@/pages/NotificationsPage'
import { UsersPage }           from '@/pages/UsersPage'
import { SettingsPage }        from '@/pages/SettingsPage'
import { ReportsPage }         from '@/pages/ReportsPage'
import { AuditPage }           from '@/pages/AuditPage'
import { AgentsPage }          from '@/pages/AgentsPage'
import { DetectionsPage }      from '@/pages/DetectionsPage'
import { AnalyticsEventsPage }    from '@/pages/AnalyticsEventsPage'
import { AnalyticsDashboardPage } from '@/pages/AnalyticsDashboardPage'
import { LGPDPage }               from '@/pages/LGPDPage'
import { SystemHealthPage }       from '@/pages/SystemHealthPage'

// Admin pages (somente role admin) — TenantsPage/AdminAuditPage/AdminSettingsPage reaproveitados;
// GMV/Pricing/Invoices dependiam do módulo billing (fora do escopo do Next Sec MVP)
import { TenantsPage }        from '@/pages/admin/TenantsPage'
import { AdminAuditPage }     from '@/pages/admin/AdminAuditPage'
import { AdminSettingsPage }  from '@/pages/admin/AdminSettingsPage'

// ─── Proteções de segurança no frontend ───────────────────────────────────────

// Desabilitar menu de contexto em produção (previne inspeção casual)
if (import.meta.env.PROD) {
  // Desabilitar atalhos de devtools
  document.addEventListener('keydown', (e) => {
    // F12, Ctrl+Shift+I, Ctrl+Shift+J, Ctrl+U
    if (
      e.key === 'F12' ||
      (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'J')) ||
      (e.ctrlKey && e.key === 'U')
    ) {
      e.preventDefault()
    }
  })
}

function RequireAuth() {
  const { isAuthenticated } = useAuthStore()
  if (!isAuthenticated()) return <Navigate to="/login" replace />
  return <Outlet />
}

function RequireAdmin() {
  const { user } = useAuthStore()
  if (user?.role !== 'admin') return <Navigate to="/dashboard" replace />
  return <Outlet />
}

function AuthenticatedApp() {
  return (
    <LicenseGate>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard"     element={<DashboardPage />} />
        <Route path="/cameras"       element={<CamerasPage />} />
        <Route path="/cameras/:id"   element={<CameraDetailPage />} />
        <Route path="/detections"    element={<DetectionsPage />} />
        <Route path="/events"        element={<AnalyticsEventsPage />} />
        <Route path="/analytics"     element={<AnalyticsDashboardPage />} />
        <Route path="/contacts"      element={<ContactsPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/agents"        element={<AgentsPage />} />
        <Route path="/reports"       element={<ReportsPage />} />
        <Route path="/audit"         element={<AuditPage />} />
        <Route path="/users"         element={<UsersPage />} />
        <Route path="/settings"      element={<SettingsPage />} />
        <Route path="/lgpd"          element={<LGPDPage />} />
        <Route path="/health"        element={<SystemHealthPage />} />

        {/* Admin routes — somente role admin */}
        <Route element={<RequireAdmin />}>
          <Route path="/admin/tenants"  element={<TenantsPage />} />
          <Route path="/admin/audit"    element={<AdminAuditPage />} />
          <Route path="/admin/settings" element={<AdminSettingsPage />} />
        </Route>

        <Route path="*"              element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
    </LicenseGate>
  )
}

export default function App() {
  return (
    <BrowserRouter
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background:   'var(--surface)',
            color:        'var(--text-1)',
            border:       '1px solid var(--border)',
            borderRadius: '10px',
            fontSize:     '13px',
          },
          success: { iconTheme: { primary: '#22C55E', secondary: '#111118' } },
          error:   { iconTheme: { primary: '#EF4444', secondary: '#111118' } },
          duration: 3000,
        }}
      />
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route element={<RequireAuth />}>
          <Route path="/*" element={<AuthenticatedApp />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
