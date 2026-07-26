import { create } from 'zustand'
import { api } from '@/services/api'

export interface LicenseStatus {
  active: boolean
  onboarding_complete: boolean
  deployment_model?: string
  license_key?: string
  max_cameras?: number
  expires_at?: string | null
  status?: string
}

interface LicenseState {
  status: LicenseStatus | null
  loading: boolean
  checked: boolean
  fetch: () => Promise<void>
  activate: (key: string) => Promise<void>
  reset: () => void
}

export const useLicenseStore = create<LicenseState>()((set, get) => ({
  status: null,
  loading: false,
  checked: false,

  fetch: async () => {
    if (get().loading) return
    set({ loading: true })
    try {
      const { data } = await api.get<LicenseStatus>('/billing/status')
      set({ status: data, checked: true })
    } catch {
      set({ status: { active: false, onboarding_complete: false }, checked: true })
    } finally {
      set({ loading: false })
    }
  },

  activate: async (key: string) => {
    await api.post('/billing/activate', { license_key: key })
    await get().fetch()
  },

  reset: () => set({ status: null, checked: false }),
}))
