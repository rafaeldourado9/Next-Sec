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

// Quadrilátero central, ocupando a maior parte do frame — ponto de partida
// pro usuário só arrastar os 4 cantos até a zona desejada.
const DEFAULT_QUAD: number[][] = [
  [0.15, 0.15],
  [0.85, 0.15],
  [0.85, 0.85],
  [0.15, 0.85],
]

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

  // A zona é sempre um quadrilátero de 4 cantos arrastáveis — sem clique pra
  // adicionar ponto (era a origem de um bug real: clicar num vértice já
  // existente também borbulhava um `click` pro SVG por baixo, adicionando um
  // ponto duplicado ali mesmo e deixando o polígono auto-intersectante, que o
  // point-in-polygon do plugin de intrusion avaliava errado — achado durante
  // teste local, "passou muita gente na cerca e não detectou"). Se a zona
  // ainda não tem os 4 pontos (nova ROI), inicializa com um retângulo padrão.
  useEffect(() => {
    if (polygon.length !== 4) onChange(DEFAULT_QUAD)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toNormalized = useCallback((e: React.MouseEvent): [number, number] | null => {
    const el = containerRef.current
    if (!el) return null
    const rect = el.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    return [round4(x), round4(y)]
  }, [])

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

  const handleReset = useCallback(() => {
    onChange(DEFAULT_QUAD)
  }, [onChange])

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
        >
          {polygon.length === 4 && (
            <polygon
              points={points}
              fill="rgba(59,130,246,0.2)"
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
            />
          ))}
        </svg>
      </div>

      {!disabled && (
        <p className="text-[11px] text-t3">
          Arraste os 4 cantos para ajustar a zona.
          <button
            className="ml-2 text-red-400 hover:text-red-300 underline"
            onClick={handleReset}
          >
            Redefinir
          </button>
        </p>
      )}
    </div>
  )
}

function round4(n: number): number {
  return Math.round(n * 10000) / 10000
}
