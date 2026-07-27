import { useEffect, useState } from 'react'

interface AuthImageState {
  blobUrl: string | null
  error: boolean
}

/** Busca uma imagem autenticada (Bearer token) e expõe como blob: URL.
 *  Extraído de AuthImage.tsx para ser reaproveitado por componentes que
 *  precisam do blob (ex.: zoom/crop) além de só renderizar um <img>. */
export function useAuthImage(src: string | null | undefined): AuthImageState {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!src) {
      setBlobUrl(null)
      setError(false)
      return
    }

    let cancelled = false
    let url: string | null = null
    setError(false)
    setBlobUrl(null)

    async function load() {
      try {
        let token: string | null = null
        try {
          const raw = localStorage.getItem('vms-auth')
          if (raw) {
            const parsed = JSON.parse(raw)
            token = parsed?.state?.tokens?.access_token ?? null
          }
        } catch { /* ignore */ }

        const r = await fetch(src as string, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const blob = await r.blob()
        url = URL.createObjectURL(blob)
        if (!cancelled) setBlobUrl(url)
      } catch {
        if (!cancelled) setError(true)
      }
    }

    load()
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [src])

  return { blobUrl, error }
}
