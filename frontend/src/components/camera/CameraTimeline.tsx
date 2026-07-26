/**
 * CameraTimeline — barra de tempo minimalista estilo NVR (redesenhada).
 *
 * Melhorias Sprint 11:
 * - Eventos marcados como ◆ na timeline com cor por severidade
 * - Tooltip ao hover mostrando hora exata + eventos no ponto
 * - Controles de playback integrados
 * - Zoom com scroll do mouse
 */
import {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react'
import {
  ChevronLeft, ChevronRight, Play, Pause, SkipBack, SkipForward,
  ZoomIn, ZoomOut,
} from 'lucide-react'
import type { RecordingSegment, VmsEvent } from '@/types'

interface Props {
  segments: RecordingSegment[]
  events?: VmsEvent[]           // eventos para marcar na timeline
  currentTime: Date
  date: string
  isPlaying?: boolean
  playbackSpeed?: number
  onSeek: (t: Date) => void
  onPlayToggle?: () => void
  onSpeedChange?: (speed: number) => void
  onDateChange?: (d: string) => void
  onDownload?: (segment: RecordingSegment) => void
  onClip?: (start: Date, end: Date) => void
}

const SPEEDS = [0.5, 1, 2, 4]
const EVENT_COLORS: Record<string, string> = {
  alpr_detected: '#f59e0b',
  default: '#f59e0b',
}

function pad(n: number) { return String(n).padStart(2, '0') }
function hhmmss(ms: number) {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function isoDate(d: Date) { return d.toISOString().split('T')[0] }

export function CameraTimeline({
  segments, events = [], currentTime, date,
  isPlaying = false, playbackSpeed = 1,
  onSeek, onPlayToggle, onSpeedChange, onDateChange,
}: Props) {
  const trackRef   = useRef<HTMLDivElement>(null)
  const dragRef    = useRef({ dragging: false, startX: 0, startView: 0 })
  const didDragRef = useRef(false)

  // Zoom level: VIEW_MS por janela
  const [viewMs, setViewMs] = useState(2 * 3600_000)  // 2h padrão

  const [viewStart, setViewStart] = useState(() => currentTime.getTime() - viewMs / 2)

  useEffect(() => {
    if (dragRef.current.dragging) return
    setViewStart(currentTime.getTime() - viewMs / 2)
  }, [currentTime, viewMs])

  const clampView = useCallback((v: number) => {
    const dayStart = new Date(date + 'T00:00:00').getTime()
    const dayEnd   = dayStart + 24 * 3600_000
    return Math.max(dayStart - viewMs / 4, Math.min(dayEnd - viewMs * 3 / 4, v))
  }, [date, viewMs])

  // ── Drag & Zoom ──────────────────────────────────────────────────────────
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragRef.current = { dragging: true, startX: e.clientX, startView: viewStart }
    didDragRef.current = false
    e.preventDefault()
  }, [viewStart])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragRef.current.dragging || !trackRef.current) return
    const dx = e.clientX - dragRef.current.startX
    if (Math.abs(dx) > 3) didDragRef.current = true
    const rect = trackRef.current.getBoundingClientRect()
    const msPx = viewMs / rect.width
    setViewStart(clampView(dragRef.current.startView - dx * msPx))
  }, [clampView, viewMs])

  const onMouseUp = useCallback((e: React.MouseEvent) => {
    if (!dragRef.current.dragging) return
    dragRef.current.dragging = false
    if (!didDragRef.current && trackRef.current) {
      const rect = trackRef.current.getBoundingClientRect()
      const pct  = (e.clientX - rect.left) / rect.width
      onSeek(new Date(viewStart + pct * viewMs))
    }
  }, [viewStart, viewMs, onSeek])

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 1 : -1
    setViewMs((prev) => {
      const steps = [15 * 60_000, 30 * 60_000, 60 * 60_000, 2 * 3600_000, 4 * 3600_000, 8 * 3600_000, 12 * 3600_000]
      const idx = steps.indexOf(prev)
      const nextIdx = Math.max(0, Math.min(steps.length - 1, idx + delta))
      return steps[nextIdx] ?? prev
    })
  }, [])

  const pan = useCallback((dir: -1 | 1) => {
    setViewStart(v => clampView(v + dir * viewMs / 3))
  }, [clampView, viewMs])

  // ── Tick marks ────────────────────────────────────────────────────────────
  const ticks = useMemo(() => {
    let interval = 10 * 60_000  // 10 min
    if (viewMs <= 30 * 60_000) interval = 1 * 60_000
    else if (viewMs <= 60 * 60_000) interval = 5 * 60_000
    else if (viewMs >= 4 * 3600_000) interval = 30 * 60_000
    else if (viewMs >= 8 * 3600_000) interval = 60 * 60_000

    const first = Math.ceil(viewStart / interval) * interval
    const marks: number[] = []
    for (let t = first; t <= viewStart + viewMs; t += interval) marks.push(t)
    return marks
  }, [viewStart, viewMs])

  // ── Segment positions ────────────────────────────────────────────────────
  const visibleSegs = useMemo(() => {
    const viewEnd = viewStart + viewMs
    return segments.filter(s => {
      const s0 = new Date(s.started_at).getTime()
      const s1 = new Date(s.ended_at).getTime()
      return s1 > viewStart && s0 < viewEnd
    }).map(s => {
      const s0   = new Date(s.started_at).getTime()
      const s1   = new Date(s.ended_at).getTime()
      const left = Math.max(0, (s0 - viewStart) / viewMs * 100)
      const right= Math.min(100, (s1 - viewStart) / viewMs * 100)
      return { key: s.id, left, width: right - left, seg: s }
    })
  }, [segments, viewStart, viewMs])

  // ── Event markers ────────────────────────────────────────────────────────
  const eventMarkers = useMemo(() => {
    return events
      .filter(ev => {
        const t = new Date(ev.occurred_at).getTime()
        return t >= viewStart && t <= viewStart + viewMs
      })
      .map(ev => {
        const t = new Date(ev.occurred_at).getTime()
        const pct = ((t - viewStart) / viewMs) * 100
        const color = EVENT_COLORS[ev.event_type] ?? EVENT_COLORS.default
        return { pct, color, type: ev.event_type, id: ev.id, time: ev.occurred_at }
      })
  }, [events, viewStart, viewMs])

  // ── Hover tooltip ────────────────────────────────────────────────────────
  const [hoverPct, setHoverPct] = useState<number | null>(null)
  const [hoverEvents, setHoverEvents] = useState<typeof eventMarkers>([])

  const onTrackMouseMove = useCallback((e: React.MouseEvent) => {
    if (!trackRef.current) return
    const rect = trackRef.current.getBoundingClientRect()
    const pct = ((e.clientX - rect.left) / rect.width) * 100
    setHoverPct(Math.max(0, Math.min(100, pct)))

    // Find events near hover point
    const hoverTime = viewStart + (pct / 100) * viewMs
    const nearby = eventMarkers.filter(ev => {
      const evTime = new Date(ev.time).getTime()
      return Math.abs(evTime - hoverTime) < 60_000  // within 1 min
    })
    setHoverEvents(nearby)
  }, [viewStart, viewMs, eventMarkers])

  const playheadPct = useMemo(() => {
    const pct = (currentTime.getTime() - viewStart) / viewMs * 100
    return pct >= 0 && pct <= 100 ? pct : null
  }, [currentTime, viewStart, viewMs])

  const today = isoDate(new Date())
  const yesterday = isoDate(new Date(Date.now() - 86400_000))
  const prevDay = isoDate(new Date(new Date(date + 'T12:00:00').getTime() - 86400_000))
  const nextDay = isoDate(new Date(new Date(date + 'T12:00:00').getTime() + 86400_000))

  const zoomIdx = [15*60_000, 30*60_000, 60*60_000, 2*3600_000, 4*3600_000, 8*3600_000, 12*3600_000].indexOf(viewMs)

  return (
    <div className="select-none animate-fade-in" style={{ userSelect: 'none' }}>
      {/* ── Date nav + controls ── */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {onDateChange && (
          <>
            <button className="w-6 h-6 flex items-center justify-center rounded text-t3 hover:text-t1 transition" onClick={() => onDateChange(prevDay)}>
              <ChevronLeft size={14} />
            </button>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <span className="text-xs text-t2 tabular-nums">
                {date === today ? 'Hoje' : date === yesterday ? 'Ontem' : date}
              </span>
              <input type="date" className="sr-only" value={date} max={today} onChange={e => e.target.value && onDateChange(e.target.value)} />
            </label>
            <button className="w-6 h-6 flex items-center justify-center rounded text-t3 hover:text-t1 transition disabled:opacity-30" onClick={() => onDateChange(nextDay)} disabled={date >= today}>
              <ChevronRight size={14} />
            </button>
          </>
        )}

        {/* Playback controls */}
        <div className="flex items-center gap-1 ml-auto">
          <button className="w-7 h-7 flex items-center justify-center rounded text-t3 hover:text-t1 transition" title="Início" onClick={() => onSeek(new Date(date + 'T00:00:00'))}>
            <SkipBack size={14} />
          </button>
          {onPlayToggle && (
            <button className="w-8 h-8 flex items-center justify-center rounded text-t1 hover:bg-elevated transition" onClick={onPlayToggle} title={isPlaying ? 'Pausar' : 'Reproduzir'}>
              {isPlaying ? <Pause size={16} /> : <Play size={16} />}
            </button>
          )}
          <button className="w-7 h-7 flex items-center justify-center rounded text-t3 hover:text-t1 transition" title="Avançar" onClick={() => onSeek(new Date(date + 'T23:59:59'))}>
            <SkipForward size={14} />
          </button>

          {/* Speed */}
          {onSpeedChange && (
            <div className="flex items-center gap-0.5 ml-1">
              {SPEEDS.map(s => (
                <button
                  key={s}
                  className={`px-1.5 py-0.5 rounded text-xs tabular-nums transition ${
                    playbackSpeed === s ? 'text-t1 bg-elevated font-semibold' : 'text-t3 hover:text-t2'
                  }`}
                  onClick={() => onSpeedChange(s)}
                >
                  {s}x
                </button>
              ))}
            </div>
          )}

          {/* Zoom */}
          <div className="flex items-center gap-0.5 ml-2 pl-2 border-l border-border">
            <button className="w-6 h-6 flex items-center justify-center rounded text-t3 hover:text-t1 transition disabled:opacity-30" disabled={zoomIdx <= 0} onClick={() => setViewMs(prev => {
              const steps = [15*60_000, 30*60_000, 60*60_000, 2*3600_000, 4*3600_000, 8*3600_000, 12*3600_000]
              const idx = steps.indexOf(prev)
              return idx > 0 ? steps[idx - 1] : prev
            })} title="Zoom in">
              <ZoomIn size={13} />
            </button>
            <button className="w-6 h-6 flex items-center justify-center rounded text-t3 hover:text-t1 transition disabled:opacity-30" disabled={zoomIdx < 0 || zoomIdx >= 6} onClick={() => setViewMs(prev => {
              const steps = [15*60_000, 30*60_000, 60*60_000, 2*3600_000, 4*3600_000, 8*3600_000, 12*3600_000]
              const idx = steps.indexOf(prev)
              return idx < steps.length - 1 ? steps[idx + 1] : prev
            })} title="Zoom out">
              <ZoomOut size={13} />
            </button>
          </div>
        </div>
      </div>

      {/* ── Track ── */}
      <div className="flex items-center gap-1">
        <button className="w-7 h-7 shrink-0 flex items-center justify-center rounded text-t3 hover:text-t1 hover:bg-elevated transition" onClick={() => pan(-1)}>
          <ChevronLeft size={16} />
        </button>

        <div className="relative flex-1 overflow-hidden" style={{ height: 56 }}>
          {/* Rail */}
          <div
            ref={trackRef}
            className="absolute inset-x-0"
            style={{ top: 8, height: 22, background: 'var(--elevated)', borderRadius: 4, cursor: 'col-resize' }}
            onMouseDown={onMouseDown}
            onMouseMove={e => { onMouseMove(e); onTrackMouseMove(e) }}
            onMouseUp={onMouseUp}
            onMouseLeave={e => { setHoverPct(null); setHoverEvents([]); if (dragRef.current.dragging) onMouseUp(e) }}
            onWheel={onWheel}
          >
            {/* Segment fills */}
            {visibleSegs.map(({ key, left, width }) => (
              <div
                key={key}
                className="absolute top-0"
                style={{
                  left:       `${left}%`,
                  width:      `${Math.max(0.3, width)}%`,
                  height:     '100%',
                  borderRadius: 3,
                  background: '#0ea5e9',
                  opacity:    0.85,
                }}
              />
            ))}

            {/* Event markers ◆ */}
            {eventMarkers.map(ev => (
              <div
                key={ev.id}
                className="absolute top-0 pointer-events-none"
                style={{
                  left: `${ev.pct}%`,
                  top: -2,
                  zIndex: 5,
                  transform: 'translateX(-50%)',
                  color: ev.color,
                  fontSize: 11,
                  lineHeight: 1,
                }}
              >
                ◆
              </div>
            ))}

            {/* Playhead */}
            {playheadPct !== null && (
              <div className="absolute top-0 bottom-0 pointer-events-none" style={{ left: `${playheadPct}%`, width: 2, background: '#ef4444', zIndex: 10 }}>
                <div style={{ position: 'absolute', top: -5, left: '50%', transform: 'translateX(-50%)', width: 0, height: 0, borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderTop: '5px solid #ef4444' }} />
              </div>
            )}

            {/* Hover tooltip */}
            {hoverPct !== null && (
              <div
                className="absolute pointer-events-none"
                style={{
                  left: `${hoverPct}%`,
                  top: -30,
                  transform: 'translateX(-50%)',
                  zIndex: 20,
                }}
              >
                <div className="bg-surface border rounded-md px-2 py-1 shadow-lg text-xs whitespace-nowrap" style={{ borderColor: 'var(--border)' }}>
                  <span className="text-t1 font-mono tabular-nums">
                    {hhmmss(viewStart + (hoverPct / 100) * viewMs)}
                  </span>
                  {hoverEvents.length > 0 && (
                    <div className="mt-0.5 flex gap-1">
                      {hoverEvents.map(ev => (
                        <span key={ev.id} style={{ color: ev.color }} title={ev.type}>◆</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Time labels */}
          <div className="absolute inset-x-0" style={{ top: 34 }}>
            {ticks.map(t => {
              const pct = (t - viewStart) / viewMs * 100
              const isHour = new Date(t).getMinutes() === 0
              return (
                <div key={t} className="absolute flex flex-col items-center pointer-events-none" style={{ left: `${pct}%`, top: 0 }}>
                  <div style={{ width: 1, height: isHour ? 5 : 3, background: isHour ? 'var(--text-3)' : 'var(--border)' }} />
                  <span className="-translate-x-1/2 tabular-nums" style={{ fontSize: 9, color: isHour ? 'var(--text-2)' : 'var(--text-3)', fontWeight: isHour ? 500 : 400, whiteSpace: 'nowrap' }}>
                    {hhmmss(t)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        <button className="w-7 h-7 shrink-0 flex items-center justify-center rounded text-t3 hover:text-t1 hover:bg-elevated transition" onClick={() => pan(1)}>
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Legend */}
      {events.length > 0 && (
        <div className="flex items-center gap-3 mt-2 text-xs text-t3">
          <span className="flex items-center gap-1">
            <span style={{ color: '#0ea5e9' }}>━</span> Gravação
          </span>
          <span className="flex items-center gap-1">
            <span style={{ color: '#f59e0b' }}>◆</span> ALPR
          </span>
        </div>
      )}
    </div>
  )
}
