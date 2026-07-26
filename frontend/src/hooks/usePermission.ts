import { useAuthStore } from '@/store/authStore'

interface PermissionResult {
  isAdmin: boolean
  isOperator: boolean
  isViewer: boolean
}

export function usePermission(): PermissionResult {
  const role = useAuthStore((s) => s.user?.role)

  return {
    isAdmin: role === 'admin',
    isOperator: role === 'admin' || role === 'operator' || role === 'gestor' || role === 'operador',
    isViewer: true,
  }
}
