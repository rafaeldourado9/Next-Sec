import { useCallback, useEffect, useRef, useState } from 'react'
import { ImageOff } from 'lucide-react'
import { camerasService } from '@/services/cameras'
import { VideoPlayer } from '@/components/camera/VideoPlayer'

interface Props {
  cameraId: string
  pointA: [number, number] | null
  pointB: [number, number] | null
  onChange: (a: [number, number], b: [number, number]) => void
  disabled?: boolean
  streamUrl?: string
}

// Dois pontos horizontais no meio do frame — ponto de partida pro usuário
// arrastar até duas marcas na cena cuja distância real ele conhece (ex: dois
// postes, duas juntas de calçada, uma faixa de pedestre).
const DEFAULT_A: [number, number] = [0.3, 0.5]
const DEFAULT_B: [number, number] = [0.7, 0.5]

export function CalibrationEditor({ cameraId, pointA, pointB, onChange, disabled, streamUrl }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [dragging, setDragging] = useState<'a' | 'b' | null>(null)

  useEffect(() => {
    if (streamUrl) { setLoading(false); return }
    setLoading(true)
    camerasService.snapshot(cameraId)
      .then(setSnapshotUrl)
      .catch(() => setSnapshotUrl(null))
      .finally(() => setLoading(false))
  }, [cameraId, streamUrl])

  useEffect(() => {
    if (!pointA || !pointB) onChange(DEFAULT_A, DEFAULT_B)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const a = pointA ?? DEFAULT_A
  const b = pointB ?? DEFAULT_B

  const toNormalized = useCallback((e: React.MouseEvent): [number, number] | null => {
    const el = containerRef.current
    if (!el) return null
    const rect = el.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    return [round4(x), round4(y)]
  }, [])

  const handleMouseDown = useCallback((which: 'a' | 'b', e: React.MouseEvent) => {
    if (disabled) return
    e.stopPropagation()
    setDragging(which)
  }, [disabled])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (dragging === null) return
    const pt = toNormalized(e)
    if (!pt) return
    if (dragging === 'a') onChange(pt, b)
    else onChange(a, pt)
  }, [dragging, a, b, onChange, toNormalized])

  const handleMouseUp = useCallback(() => setDragging(null), [])

  if (loading) {
    return (
      <div className="w-full aspect-video rounded-lg animate-pulse" style={{ background: 'var(--elevated)' }} />
    )
  }

  return (
    <div className="space-y-2">
      <div
        ref={containerRef}
        className="relative w-full aspect-video rounded-lg overflow-hidden border select-none"
        style={{ borderColor: 'var(--border)', background: '#000' }}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {streamUrl ? (
          <VideoPlayer src={streamUrl} className="absolute inset-0 w-full h-full !rounded-none" muted autoPlay />
        ) : snapshotUrl ? (
          <img src={snapshotUrl} alt="Camera snapshot" className="w-full h-full object-contain" draggable={false} />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-t3">
            <ImageOff size={32} />
            <span className="text-xs">Snapshot indisponivel</span>
          </div>
        )}

        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 1 1" preserveAspectRatio="none">
          <line
            x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
            stroke="rgba(234,179,8,0.9)" strokeWidth="0.004" strokeDasharray="0.01 0.008"
          />
          <circle
            cx={a[0]} cy={a[1]} r={dragging === 'a' ? 0.018 : 0.012}
            fill={dragging === 'a' ? '#eab308' : 'rgba(234,179,8,0.9)'}
            stroke="#fff" strokeWidth="0.003"
            style={{ cursor: disabled ? 'default' : 'grab' }}
            onMouseDown={(e) => handleMouseDown('a', e)}
          />
          <circle
            cx={b[0]} cy={b[1]} r={dragging === 'b' ? 0.018 : 0.012}
            fill={dragging === 'b' ? '#eab308' : 'rgba(234,179,8,0.9)'}
            stroke="#fff" strokeWidth="0.003"
            style={{ cursor: disabled ? 'default' : 'grab' }}
            onMouseDown={(e) => handleMouseDown('b', e)}
          />
        </svg>
      </div>

      {!disabled && (
        <p className="text-[11px] text-t3">
          Arraste os pontos <strong>A</strong> e <strong>B</strong> até duas marcas na cena (ex: dois postes, uma faixa de pedestre) cuja distância real você sabe — informe essa distância no campo abaixo.
        </p>
      )}
    </div>
  )
}

function round4(n: number): number {
  return Math.round(n * 10000) / 10000
}
