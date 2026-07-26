import { useCallback, useEffect, useRef, useState } from 'react'
import { ImageOff } from 'lucide-react'
import { camerasService } from '@/services/cameras'
import { VideoPlayer } from '@/components/camera/VideoPlayer'

interface Props {
  cameraId: string
  polygon: number[][]
  onChange: (polygon: number[][]) => void
  disabled?: boolean
  streamUrl?: string
}

export function PolygonEditor({ cameraId, polygon, onChange, disabled, streamUrl }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [dragging, setDragging] = useState<number | null>(null)

  useEffect(() => {
    if (streamUrl) { setLoading(false); return }
    setLoading(true)
    camerasService.snapshot(cameraId)
      .then(setSnapshotUrl)
      .catch(() => setSnapshotUrl(null))
      .finally(() => setLoading(false))
  }, [cameraId, streamUrl])

  const toNormalized = useCallback((e: React.MouseEvent): [number, number] | null => {
    const el = containerRef.current
    if (!el) return null
    const rect = el.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    return [round4(x), round4(y)]
  }, [])

  const handleClick = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (disabled || dragging !== null) return
    const pt = toNormalized(e)
    if (!pt) return
    onChange([...polygon, pt])
  }, [disabled, dragging, polygon, onChange, toNormalized])

  const handleVertexMouseDown = useCallback((idx: number, e: React.MouseEvent) => {
    if (disabled) return
    e.stopPropagation()
    setDragging(idx)
  }, [disabled])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (dragging === null) return
    const pt = toNormalized(e)
    if (!pt) return
    const next = [...polygon]
    next[dragging] = pt
    onChange(next)
  }, [dragging, polygon, onChange, toNormalized])

  const handleMouseUp = useCallback(() => {
    setDragging(null)
  }, [])

  const handleVertexDoubleClick = useCallback((idx: number, e: React.MouseEvent) => {
    e.stopPropagation()
    if (disabled || polygon.length <= 3) return
    onChange(polygon.filter((_, i) => i !== idx))
  }, [disabled, polygon, onChange])

  const points = polygon.map(([x, y]) => `${x},${y}`).join(' ')

  if (loading) {
    return (
      <div
        className="w-full aspect-video rounded-lg animate-pulse"
        style={{ background: 'var(--elevated)' }}
      />
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
          <VideoPlayer
            src={streamUrl}
            className="absolute inset-0 w-full h-full !rounded-none"
            muted
            autoPlay
          />
        ) : snapshotUrl ? (
          <img
            src={snapshotUrl}
            alt="Camera snapshot"
            className="w-full h-full object-contain"
            draggable={false}
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-t3">
            <ImageOff size={32} />
            <span className="text-xs">Snapshot indisponivel</span>
          </div>
        )}

        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          onClick={handleClick}
          style={{ cursor: disabled ? 'default' : 'crosshair' }}
        >
          {polygon.length >= 3 && (
            <polygon
              points={points}
              fill="rgba(59,130,246,0.2)"
              stroke="rgba(59,130,246,0.8)"
              strokeWidth="0.003"
            />
          )}
          {polygon.length > 0 && polygon.length < 3 && (
            <polyline
              points={points}
              fill="none"
              stroke="rgba(59,130,246,0.8)"
              strokeWidth="0.003"
            />
          )}
          {polygon.map(([x, y], i) => (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={dragging === i ? 0.018 : 0.012}
              fill={dragging === i ? '#3b82f6' : 'rgba(59,130,246,0.9)'}
              stroke="#fff"
              strokeWidth="0.003"
              style={{ cursor: disabled ? 'default' : 'grab' }}
              onMouseDown={(e) => handleVertexMouseDown(i, e)}
              onDoubleClick={(e) => handleVertexDoubleClick(i, e)}
            />
          ))}
        </svg>
      </div>

      {!disabled && (
        <p className="text-[11px] text-t3">
          Clique para adicionar pontos. Arraste para mover. Duplo-clique para remover.
          {polygon.length > 0 && (
            <button
              className="ml-2 text-red-400 hover:text-red-300 underline"
              onClick={() => onChange([])}
            >
              Limpar tudo
            </button>
          )}
        </p>
      )}
    </div>
  )
}

function round4(n: number): number {
  return Math.round(n * 10000) / 10000
}
