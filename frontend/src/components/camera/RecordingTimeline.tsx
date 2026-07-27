import { useCallback, useEffect, useRef, useState } from 'react'
import { camerasService, type RecordingRange } from '@/services/cameras'
import { getEventTypeColor } from '@/constants/eventTypes'
import type { VmsEvent } from '@/types'

interface RecordingTimelineProps {
  cameraId: string
  windowStart: Date
  windowEnd: Date
  events?: VmsEvent[]
  onSeek: (t: Date) => void
  selected?: Date | null
}

function pct(t: number, start: number, end: number): number {
  if (end <= start) return 0
  return Math.min(100, Math.max(0, ((t - start) / (end - start)) * 100))
}

/** Scrubber horizontal — sombreia trechos com gravação disponível (busca em
 *  /recordings/availability) e marca eventos já conhecidos (reaproveita o
 *  que a aba de eventos já buscou, sem taxonomia nova). Clicar/arrastar
 *  chama onSeek com o horário correspondente à posição. */
export function RecordingTimeline({
  cameraId, windowStart, windowEnd, events = [], onSeek, selected,
}: RecordingTimelineProps) {
  const [ranges, setRanges] = useState<RecordingRange[]>([])
  const [loading, setLoading] = useState(true)
  const trackRef = useRef<HTMLDivElement>(null)
  const [hoverPct, setHoverPct] = useState<number | null>(null)

  const startMs = windowStart.getTime()
  const endMs = windowEnd.getTime()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await camerasService.recordingsAvailability(
        cameraId, windowStart.toISOString(), windowEnd.toISOString(),
      )
      setRanges(res.ranges)
    } catch {
      setRanges([])
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, windowStart.getTime(), windowEnd.getTime()])

  useEffect(() => {
    const id = setTimeout(load, 200) // debounce — pan/zoom dispara várias mudanças seguidas
    return () => clearTimeout(id)
  }, [load])

  const timeFromClientX = useCallback((clientX: number): Date | null => {
    const el = trackRef.current
    if (!el) return null
    const rect = el.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return new Date(startMs + ratio * (endMs - startMs))
  }, [startMs, endMs])

  const handleClick = (e: React.MouseEvent) => {
    const t = timeFromClientX(e.clientX)
    if (t) onSeek(t)
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    const el = trackRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setHoverPct(((e.clientX - rect.left) / rect.width) * 100)
  }

  const fmt = (d: Date) => d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="select-none">
      <div className="flex items-center justify-between mb-1.5 text-[10px] text-t3">
        <span>{fmt(windowStart)}</span>
        {loading && <span className="text-t3/60">carregando cobertura...</span>}
        <span>{fmt(windowEnd)}</span>
      </div>

      <div
        ref={trackRef}
        onClick={handleClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverPct(null)}
        className="relative h-10 rounded-lg cursor-pointer overflow-hidden"
        style={{ background: 'var(--elevated)', border: '1px solid var(--border)' }}
      >
        {/* Trechos com gravação disponível */}
        {ranges.map((r, i) => {
          const rStart = pct(new Date(r.start).getTime(), startMs, endMs)
          const rEnd = pct(new Date(r.end).getTime(), startMs, endMs)
          return (
            <div
              key={i}
              className="absolute top-0 bottom-0"
              style={{
                left: `${rStart}%`,
                width: `${Math.max(0.3, rEnd - rStart)}%`,
                background: 'color-mix(in srgb, var(--accent) 35%, transparent)',
              }}
              title={`Gravado: ${new Date(r.start).toLocaleString('pt-BR')} — ${new Date(r.end).toLocaleString('pt-BR')}`}
            />
          )
        })}

        {/* Marcadores de eventos já conhecidos */}
        {events.map(ev => {
          const t = new Date(ev.occurred_at).getTime()
          if (t < startMs || t > endMs) return null
          const color = getEventTypeColor(ev.event_type)
          return (
            <div
              key={ev.id}
              className="absolute top-0.5 w-0.5 h-2 rounded-full"
              style={{ left: `${pct(t, startMs, endMs)}%`, background: color.text }}
              title={`${ev.event_type} — ${new Date(ev.occurred_at).toLocaleTimeString('pt-BR')}`}
            />
          )
        })}

        {/* Posição selecionada */}
        {selected && (
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-white shadow"
            style={{ left: `${pct(selected.getTime(), startMs, endMs)}%` }}
          />
        )}

        {/* Linha de hover */}
        {hoverPct !== null && (
          <div
            className="absolute top-0 bottom-0 w-px pointer-events-none"
            style={{ left: `${hoverPct}%`, background: 'rgba(255,255,255,0.3)' }}
          />
        )}

        {!loading && ranges.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-[10px] text-t3/60">
            Sem gravação neste período
          </div>
        )}
      </div>
    </div>
  )
}
