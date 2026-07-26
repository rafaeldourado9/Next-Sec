import { useEffect, useRef, useState } from 'react'
import { Camera as CameraIcon } from 'lucide-react'
import { clsx } from 'clsx'
import { useAuthStore } from '@/store/authStore'

interface ThumbnailProps {
  cameraId: string
  className?: string
}

// ── IndexedDB cache (24h TTL, stale-while-revalidate) ────────────────────────
const IDB_NAME = 'vms-thumbs'
const IDB_STORE = 'frames'
const IDB_TTL = 24 * 60 * 60 * 1000 // 24h

let _db: Promise<IDBDatabase> | null = null

function openDB(): Promise<IDBDatabase> {
  if (!_db) {
    _db = new Promise((res, rej) => {
      const r = indexedDB.open(IDB_NAME, 1)
      r.onupgradeneeded = () => r.result.createObjectStore(IDB_STORE)
      r.onsuccess = () => res(r.result)
      r.onerror = () => rej(r.error)
    })
  }
  return _db
}

async function idbGet(id: string): Promise<Blob | null> {
  try {
    const db = await openDB()
    return new Promise((res) => {
      const req = db.transaction(IDB_STORE).objectStore(IDB_STORE).get(id)
      req.onsuccess = () => {
        const v = req.result as { blob: Blob; ts: number } | undefined
        res(v && Date.now() - v.ts < IDB_TTL ? v.blob : null)
      }
      req.onerror = () => res(null)
    })
  } catch {
    return null
  }
}

async function idbSet(id: string, blob: Blob): Promise<void> {
  try {
    const db = await openDB()
    db.transaction(IDB_STORE, 'readwrite').objectStore(IDB_STORE).put({ blob, ts: Date.now() }, id)
  } catch {
    /* ignore */
  }
}

// ── In-memory blob URL pool (survives re-renders, avoids duplicate fetches) ──
const blobPool = new Map<string, string>()

function poolSet(id: string, blob: Blob): string {
  const old = blobPool.get(id)
  if (old) URL.revokeObjectURL(old)
  const url = URL.createObjectURL(blob)
  blobPool.set(id, url)
  return url
}

// ── Component ────────────────────────────────────────────────────────────────
export function Thumbnail({ cameraId, className }: ThumbnailProps) {
  const [src, setSrc] = useState<string | null>(() => blobPool.get(cameraId) ?? null)
  const [loaded, setLoaded] = useState(() => blobPool.has(cameraId))
  const [error, setError] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const token = useAuthStore((s) => s.tokens?.access_token ?? '')

  useEffect(() => {
    if (!token) {
      setSrc(null)
      setLoaded(false)
      return
    }

    let cancelled = false
    setError(false)

    // 1. Sync from blobPool immediately (same session, no flicker)
    const pooled = blobPool.get(cameraId)
    if (pooled) {
      setSrc(pooled)
      setLoaded(true)
    } else {
      setSrc(null)
      setLoaded(false)

      // 2. IDB cache: show immediately while network refreshes
      idbGet(cameraId).then((blob) => {
        if (cancelled || !blob) return
        const url = poolSet(cameraId, blob)
        setSrc(url)
        setLoaded(true)
      })
    }

    // 3. Always fetch fresh when visible (stale-while-revalidate)
    const el = containerRef.current
    if (!el) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) return
        observer.disconnect()

        const endpoint = `/api/v1/cameras/${cameraId}/thumbnail?token=${encodeURIComponent(token)}`
        fetch(endpoint)
          .then((r) => {
            if (!r.ok) throw r
            return r.blob()
          })
          .then((blob) => {
            if (cancelled) return
            void idbSet(cameraId, blob)
            const url = poolSet(cameraId, blob)
            setSrc(url)
            setLoaded(true)
            setError(false)
          })
          .catch(() => {
            if (!cancelled && !blobPool.has(cameraId)) setError(true)
          })
      },
      { rootMargin: '300px' },
    )
    observer.observe(el)

    return () => {
      cancelled = true
      observer.disconnect()
    }
  }, [cameraId, token])

  // Clear pool on logout
  useEffect(() => {
    if (!token) {
      blobPool.forEach((url) => URL.revokeObjectURL(url))
      blobPool.clear()
      setSrc(null)
      setLoaded(false)
    }
  }, [token])

  return (
    <div ref={containerRef} className={clsx('relative w-full h-full overflow-hidden', className)}>
      {/* Skeleton enquanto carrega */}
      {!loaded && !error && (
        <div className="absolute inset-0 animate-pulse bg-zinc-800" />
      )}

      {/* Thumbnail */}
      {src && (
        <img
          src={src}
          alt=""
          decoding="async"
          className={clsx(
            'absolute inset-0 w-full h-full object-cover transition-opacity duration-200',
            loaded ? 'opacity-100' : 'opacity-0',
          )}
          onLoad={() => {
            setLoaded(true)
            setError(false)
          }}
          onError={() => {
            setLoaded(false)
            setError(true)
          }}
        />
      )}

      {/* Erro / offline */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-900">
          <CameraIcon size={14} className="text-zinc-700" />
        </div>
      )}
    </div>
  )
}
