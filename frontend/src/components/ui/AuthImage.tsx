import { useEffect, useState } from 'react'
import { Camera } from 'lucide-react'

export function AuthImage({ src, alt, className, style, onClick }: {
  src: string
  alt?: string
  className?: string
  style?: React.CSSProperties
  onClick?: (e: React.MouseEvent) => void
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
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

        const r = await fetch(src, {
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

  if (error || !blobUrl) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-1 ${className ?? ''}`}
        style={style}
      >
        <Camera size={16} style={{ color: 'rgba(255,255,255,0.12)' }} />
        <span className="text-[8px] text-t3/40">Sem imagem</span>
      </div>
    )
  }

  return (
    <img src={blobUrl} alt={alt} className={className} style={style} onClick={onClick} />
  )
}
