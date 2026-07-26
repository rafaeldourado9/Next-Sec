/**
 * DetectionOverlay — renderiza bounding boxes de detecções sobre o vídeo.
 *
 * Uso: sobrepor ao <video> ou <canvas> do player.
 *
 * <div style={{ position: 'relative' }}>
 *   <VideoPlayer ... />
 *   <DetectionOverlay detections={detections} showOverlay={showDetections} />
 * </div>
 */
import { useMemo } from 'react'

export interface Detection {
  class_id: string       // 'person', 'car', etc.
  confidence: number     // 0-1
  x: number              // normalizado 0-1
  y: number              // normalizado 0-1
  width: number          // normalizado 0-1
  height: number         // normalizado 0-1
  track_id?: number      // ID do tracker (opcional)
}

interface Props {
  detections: Detection[]
  showLabels?: boolean
  showBoxes?: boolean
  /** Mapa de classe → cor (hex) */
  classColors?: Record<string, string>
}

const DEFAULT_COLORS: Record<string, string> = {
  person:          '#22c55e',
  bicycle:         '#f59e0b',
  car:             '#3b82f6',
  motorcycle:      '#8b5cf6',
  bus:             '#ec4899',
  truck:           '#14b8a6',
  fire:            '#ef4444',
  smoke:           '#6b7280',
  dog:             '#f97316',
  cat:             '#a855f7',
  bird:            '#06b6d4',
  helmet:          '#eab308',
  vest:            '#22c55e',
  // analytics plugin types
  intrusion:       '#ef4444',
  people_count:    '#3b82f6',
  vehicle_count:   '#8b5cf6',
  face:            '#ec4899',
  plate:           '#f59e0b',
}

export function DetectionOverlay({
  detections,
  showLabels = true,
  showBoxes = true,
  classColors = DEFAULT_COLORS,
}: Props) {
  const rendered = useMemo(() => {
    if (detections.length === 0) return null

    return detections.map((det, i) => {
      const color = classColors[det.class_id] ?? '#888888'
      const left = det.x * 100
      const top = det.y * 100
      const w = det.width * 100
      const h = det.height * 100
      const pct = Math.round(det.confidence * 100)

      return (
        <div
          key={det.track_id ?? i}
          className="absolute pointer-events-none"
          style={{
            left: `${left}%`,
            top: `${top}%`,
            width: `${w}%`,
            height: `${h}%`,
            zIndex: 5,
          }}
        >
          {/* Bounding box */}
          {showBoxes && (
            <div
              className="absolute inset-0"
              style={{
                border: `2px solid ${color}`,
                borderRadius: 3,
                opacity: 0.8,
              }}
            />
          )}

          {/* Label */}
          {showLabels && (
            <div
              className="absolute -top-5 left-0 whitespace-nowrap px-1 py-0.5 rounded text-[10px] font-mono font-semibold"
              style={{
                background: color,
                color: '#000',
                fontSize: 9,
                lineHeight: '14px',
              }}
            >
              {det.class_id} {pct}%
              {det.track_id !== undefined && ` #${det.track_id}`}
            </div>
          )}
        </div>
      )
    })
  }, [detections, showLabels, showBoxes, classColors])

  if (!rendered) return null

  return (
    <div className="absolute inset-0" style={{ zIndex: 5, pointerEvents: 'none' }}>
      {rendered}
    </div>
  )
}
