import { useEffect } from 'react'
import { useThemeStore } from '@/store/themeStore'
import { api } from '@/services/api'

interface TenantThemeResponse {
  name?: string
  primary_color?: string
  logo_url?: string | null
  system_name?: string
}

export function useTheme() {
  const { accentColor, logoUrl, systemName, setTheme } = useThemeStore()

  useEffect(() => {
    api.get<TenantThemeResponse>('/tenants/me')
      .then(({ data }) => {
        setTheme({
          accentColor: data.primary_color,
          logoUrl: data.logo_url,
          systemName: data.system_name ?? data.name,
        })
      })
      .catch(() => {
        // endpoint may not exist yet — keep persisted values
      })
  }, [setTheme])

  useEffect(() => {
    document.documentElement.style.setProperty('--accent', accentColor)
  }, [accentColor])

  useEffect(() => {
    document.title = systemName
  }, [systemName])

  return { primaryColor: accentColor, logo: logoUrl, systemName }
}
